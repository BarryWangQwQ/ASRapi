
import logging
import tensorflow as tf
import tensorflow.keras.mixed_precision.experimental as mixed_precision

from utils.speech_featurizers import SpeechFeaturizer
from utils.text_featurizers import TextFeaturizer

from trainer.base_runners import BaseTrainer



class LASTrainer(BaseTrainer):
    """ Trainer for CTC Models """

    def __init__(self,
                 speech_featurizer: SpeechFeaturizer,
                 text_featurizer: TextFeaturizer,
                 config: dict,
                 is_mixed_precision: bool = False,
                 strategy=None
                 ):
        super(LASTrainer, self).__init__(config=config,)
        self.speech_featurizer = speech_featurizer
        self.text_featurizer = text_featurizer
        self.is_mixed_precision = is_mixed_precision
        self.set_strategy(strategy)
    def set_train_metrics(self):
        lists=['classes_loss','stop_loss']
        if self.config['guide_attention']:
            lists+=['alig_guide_loss']
        self.train_metrics={}
        for item in lists:
            self.train_metrics.update({
            item: tf.keras.metrics.Mean("train_{}".format(item), dtype=tf.float32)
        })

    def set_eval_metrics(self):
        lists = ['classes_loss', 'stop_loss']
        if self.config['guide_attention']:
            lists += ['alig_guide_loss']
        self.eval_metrics={}
        for item in lists:
            self.eval_metrics.update({
            item: tf.keras.metrics.Mean("eval_{}".format(item), dtype=tf.float32),
        })

    @tf.function(experimental_relax_shapes=True)
    def _train_step(self, batch):
        features,  input_length, labels, label_length,guide_matrix= batch
        max_iter=tf.shape(labels)[1]
        self.model.maxinum_iterations = max_iter
        with tf.GradientTape() as tape:


            y_pred, stop_token_pred, aligments = self.model([features,
                                                                input_length],
                                                                tf.expand_dims(labels, -1),
                                                                label_length,
                                                                training=True)


            classes_loss = self.mask_loss(labels,y_pred)
            stop_loss=self.stop_loss(labels,stop_token_pred)
            if self.config['guide_attention']:
                real_length=tf.shape(y_pred)[1]
                alig_loss=self.alig_loss(guide_matrix[:,:real_length],aligments[:,:real_length])
                train_loss=classes_loss+stop_loss+alig_loss
            else:
                train_loss = classes_loss + stop_loss
            train_loss = tf.nn.compute_average_loss(train_loss,
                                                    global_batch_size=self.global_batch_size)
            if self.is_mixed_precision:
                scaled_train_loss = self.optimizer.get_scaled_loss(train_loss)

        if self.is_mixed_precision:
            scaled_gradients = tape.gradient(scaled_train_loss, self.model.trainable_variables)
            gradients = self.optimizer.get_unscaled_gradients(scaled_gradients)
        else:
            gradients = tape.gradient(train_loss, self.model.trainable_variables)
        self.optimizer.apply_gradients(zip(gradients, self.model.trainable_variables))

        self.train_metrics['classes_loss'].update_state(classes_loss)
        self.train_metrics["stop_loss"].update_state(stop_loss)
        if self.config['guide_attention']:
            self.train_metrics["alig_guide_loss"].update_state(alig_loss)




    @tf.function(experimental_relax_shapes=True)
    def _eval_step(self, batch):
        features, input_length, labels, label_length, guide_matrix = batch

        max_iter = tf.shape(labels)[1]
        self.model.maxinum_iterations=max_iter


        y_pred, stop_token_pred, aligments = self.model([features,
                                                        input_length],
                                                        tf.expand_dims(labels, -1),
                                                        label_length,
                                                         training=False)

        classes_loss = self.mask_loss(labels, y_pred)
        stop_loss = self.stop_loss(labels, stop_token_pred)
        if self.config['guide_attention']:
            real_length = tf.shape(y_pred)[1]
            alig_loss = self.alig_loss(guide_matrix[:, :real_length], aligments[:, :real_length])

        self.eval_metrics['classes_loss'].update_state(classes_loss)
        self.eval_metrics["stop_loss"].update_state(stop_loss)
        if self.config['guide_attention']:
            self.eval_metrics["alig_guide_loss"].update_state(alig_loss)


    def stop_loss(self,labels,y_pred):
        y_true=tf.cast(tf.equal(labels,self.text_featurizer.pad),1.)
        loss=tf.keras.losses.binary_crossentropy(y_true,y_pred,True)
        return loss

    def mask_loss(self,y_true,y_pred):
        mask=tf.cast(tf.not_equal(y_true,self.text_featurizer.pad),1.)
        loss=tf.keras.losses.sparse_categorical_crossentropy(y_true,y_pred,True)
        mask_loss=loss*mask
        total_loss=tf.reduce_mean(tf.reduce_sum(mask_loss,-1)/(tf.reduce_sum(mask,-1)+1e-6),-1)
        return tf.reduce_sum(total_loss)
    def alig_loss(self,guide_matrix,y_pred):
        attention_masks = tf.cast(tf.math.not_equal(guide_matrix, -1.0), tf.float32)
        loss_att = tf.reduce_sum(
            tf.abs(y_pred * guide_matrix) * attention_masks,-1
        )
        loss_att /= tf.reduce_sum(attention_masks,-1)
        return tf.reduce_sum(loss_att)
    def compile(self, model: tf.keras.Model,
                optimizer: any,
                max_to_keep: int = 10):
        f,c=self.speech_featurizer.compute_feature_dim()
        with self.strategy.scope():
            self.model = model
            if self.model.mel_layer is not None:
                self.model._build([1, 16000,1], training=True)
            else:
                self.model._build([1, 80, f, c],training=True)
            try:
                self.load_checkpoint()
            except:
                logging.info('trainer resume failed')
            self.optimizer = tf.keras.optimizers.get(optimizer)

            if self.is_mixed_precision:
                self.optimizer = mixed_precision.LossScaleOptimizer(self.optimizer, "dynamic")

        self.set_progbar()
        # self.load_checkpoint()

    def fit(self, epoch=None):
        if epoch is not None:
            self.epochs=epoch
            self.train_progbar.set_description_str(
                f"[Train] [Epoch {epoch}/{self.config['num_epochs']}]")


        self._train_batches()

        self._check_eval_interval()

