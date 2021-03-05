

import tensorflow as tf
import tensorflow.keras.mixed_precision.experimental as mixed_precision

from trainer.base_runners import BaseTrainer
from losses.rnnt_losses import USE_TF,tf_rnnt_loss,rnnt_loss
from AMmodel.transducer_wrap import Transducer
from utils.text_featurizers import TextFeaturizer
import logging

class TransducerTrainer(BaseTrainer):
    def __init__(self,
                 speech_featurizer,
                 text_featurizer: TextFeaturizer,
                 config: dict,
                 is_mixed_precision: bool = False,
                 strategy=None
                ):
        """
        Args:
            config: the 'running_config' part in YAML config file'
            text_featurizer: the TextFeaturizer instance
            is_mixed_precision: a boolean for using mixed precision or not
        """
        super(TransducerTrainer, self).__init__(config)
        self.speech_featurizer=speech_featurizer
        self.text_featurizer = text_featurizer
        self.is_mixed_precision = is_mixed_precision
        self.set_strategy(strategy)
        if USE_TF:
            self.rnnt_loss=tf_rnnt_loss
        else:
            self.rnnt_loss=rnnt_loss
    def set_train_metrics(self):
        self.train_metrics = {
            "transducer_loss": tf.keras.metrics.Mean("train_transducer_loss", dtype=tf.float32)
        }

    def set_eval_metrics(self):
        self.eval_metrics = {
            "transducer_loss": tf.keras.metrics.Mean("eval_transducer_loss", dtype=tf.float32)
        }

    @tf.function(experimental_relax_shapes=True)
    def _train_step(self, batch):
        features,  input_length, labels, label_length = batch
        pred_inp=labels
        target=labels[:,1:]
        label_length-=1

        with tf.GradientTape() as tape:


            logits = self.model([features, pred_inp], training=True)
            # print(logits.shape,target.shape)
            if USE_TF:
                per_train_loss=self.rnnt_loss(logits=logits, labels=target
                                              , label_length=label_length, logit_length=input_length)
            else:
                per_train_loss = self.rnnt_loss(
                logits=logits, labels=labels, label_length=label_length,
                logit_length=(input_length // self.model.time_reduction_factor),
                blank=self.text_featurizer.blank)

            train_loss = tf.nn.compute_average_loss(per_train_loss,
                                                    global_batch_size=self.global_batch_size)

            if self.is_mixed_precision:
                scaled_train_loss = self.optimizer.get_scaled_loss(train_loss)

        if self.is_mixed_precision:
            scaled_gradients = tape.gradient(scaled_train_loss, self.model.trainable_variables)
            gradients = self.optimizer.get_unscaled_gradients(scaled_gradients)
        else:
            gradients = tape.gradient(train_loss, self.model.trainable_variables)
        self.optimizer.apply_gradients(zip(gradients, self.model.trainable_variables))

        self.train_metrics["transducer_loss"].update_state(per_train_loss)

    @tf.function(experimental_relax_shapes=True)
    def _eval_step(self, batch):
        features,input_length, labels, label_length = batch
        pred_inp = labels
        target = labels[:, 1:]
        label_length -= 1


        logits = self.model([features, pred_inp], training=False)
        if USE_TF:
            eval_loss = self.rnnt_loss(logits=logits, labels=target
                                            , label_length=label_length,
                                            logit_length=input_length,
                                           )
        else:
            eval_loss = self.rnnt_loss(
                logits=logits, labels=target, label_length=label_length,
                logit_length=(input_length // self.model.time_reduction_factor),
                blank=self.text_featurizer.blank)

        self.eval_metrics["transducer_loss"].update_state(eval_loss)

    def compile(self,
                model: Transducer,
                optimizer: any,
                max_to_keep: int = 10):
        f, c = self.speech_featurizer.compute_feature_dim()
        with self.strategy.scope():
            self.model = model
            if self.model.mel_layer is not None:
                self.model._build([1, 16000, 1])
            else:
                self.model._build([1, 80, f, c])
            self.model.summary(line_length=100)
            try:
                self.load_checkpoint()
            except:
                logging.info('trainer resume failed,use init state')
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
