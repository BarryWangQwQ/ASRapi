from utils.speech_featurizers import SpeechFeaturizer
from utils.text_featurizers import TextFeaturizer
import pypinyin
import numpy as np
from augmentations.augments import Augmentation
import random
import tensorflow as tf
import os
class AM_DataLoader():

    def __init__(self, config_dict,training=True):
        self.speech_config = config_dict['speech_config']


        self.text_config = config_dict['decoder_config']
        self.augment_config = config_dict['augments_config']

        self.batch = config_dict['learning_config']['running_config']['batch_size']
        self.speech_featurizer = SpeechFeaturizer(self.speech_config)
        self.text_featurizer = TextFeaturizer(self.text_config)
        self.make_file_list(self.speech_config['train_list'] if training else self.speech_config['eval_list'],training)
        self.augment = Augmentation(self.augment_config)
        self.init_text_to_vocab()
        self.epochs = 1
        self.LAS=False
        self.steps = 0
    def load_state(self,outdir):
        try:
            self.pick_index=np.load(os.path.join(outdir,'dg_state.npy')).flatten().tolist()
            self.epochs=1+int(np.mean(self.pick_index))
        except FileNotFoundError:
            print('not found dataloader state file,use init state')
        except:
            print('load state falied,use init state')
    def save_state(self,outdir):
        np.save(os.path.join(outdir,'dg_state.npy'),np.array(self.pick_index))

    def return_data_types(self):
        if self.LAS:
            return (tf.float32, tf.float32, tf.int32, tf.int32, tf.int32,tf.float32)
        else:
            return  (tf.float32, tf.int32, tf.int32, tf.int32)
    def return_data_shape(self):
        f,c=self.speech_featurizer.compute_feature_dim()
        if self.LAS:
            return (
                tf.TensorShape([None,None,1]) if self.speech_config['use_mel_layer'] else  tf.TensorShape([None,None,f,c]),

                tf.TensorShape([None,]),
                tf.TensorShape([None,None]),
                tf.TensorShape([None,]),
                tf.TensorShape([None,None,None])
            )
        else:
            return (
                tf.TensorShape([None, None, 1]) if self.speech_config['use_mel_layer'] else tf.TensorShape(
                    [None, None, f, c]),

                tf.TensorShape([None, ]),
                tf.TensorShape([None, None]),
                tf.TensorShape([None, ])
            )
    def get_per_epoch_steps(self):
        return len(self.train_list)//self.batch
    def eval_per_epoch_steps(self):
        return len(self.test_list)//self.batch
    def init_text_to_vocab(self):
        pypinyin.load_phrases_dict({'调大': [['tiáo'], ['dà']],
                                    '调小': [['tiáo'], ['xiǎo']],
                                    '调亮': [['tiáo'], ['liàng']],
                                    '调暗': [['tiáo'], ['àn']],
                                    '肖': [['xiāo']],
                                    '英雄传': [['yīng'], ['xióng'], ['zhuàn']],
                                    '新传': [['xīn'], ['zhuàn']],
                                    '外传': [['wài'], ['zhuàn']],
                                    '正传': [['zhèng'], ['zhuàn']], '水浒传': [['shuǐ'], ['hǔ'], ['zhuàn']]
                                    })

        def text_to_vocab_func(txt):
            pins=pypinyin.pinyin(txt)
            pins=[i[0] for i in pins]
            return pins

        self.text_to_vocab = text_to_vocab_func

    def augment_data(self, wavs, label, label_length):
        if not self.augment.available():
            return None
        mels = []
        input_length = []
        label_ = []
        label_length_ = []
        wavs_ = []
        max_input = 0
        max_wav = 0
        for idx, wav in enumerate(wavs):

            data = self.augment.process(wav.flatten())
            speech_feature = self.speech_featurizer.extract(data)
            if speech_feature.shape[0] // self.speech_config['reduction_factor'] < label_length[idx]:
                continue
            max_input = max(max_input, speech_feature.shape[0])

            max_wav = max(max_wav, len(data))

            wavs_.append(data)

            mels.append(speech_feature)
            input_length.append(speech_feature.shape[0] // self.speech_config['reduction_factor'])
            label_.append(label[idx])
            label_length_.append(label_length[idx])

        for i in range(len(mels)):
            if mels[i].shape[0] < max_input:
                pad = np.ones([max_input - mels[i].shape[0], mels[i].shape[1],mels[i].shape[2]]) * mels[i].min()
                mels[i] = np.vstack((mels[i], pad))

        wavs_ = self.speech_featurizer.pad_signal(wavs_, max_wav)

        x = np.array(mels, 'float32')
        label_ = np.array(label_, 'int32')

        input_length = np.array(input_length, 'int32')
        label_length_ = np.array(label_length_, 'int32')

        wavs_ = np.array(np.expand_dims(wavs_, -1), 'float32')

        return x, wavs_, input_length, label_, label_length_

    def make_file_list(self, wav_list,training=True):
        with open(wav_list, encoding='utf-8') as f:
            data = f.readlines()
        data=[i.strip()  for i in data if i!='']
        num = len(data)
        if training:
            self.train_list = data[:int(num * 0.99)]
            self.test_list = data[int(num * 0.99):]
            np.random.shuffle(self.train_list)
            self.pick_index = [0.] * len(self.train_list)
        else:
            self.test_list=data
            self.offset=0
    def only_chinese(self, word):
        txt=''
        for ch in word:
            if '\u4e00' <= ch <= '\u9fff':
                txt+=ch
            else:
                continue

        return txt
    def eval_data_generator(self):
        sample=self.test_list[self.offset:self.offset+self.batch]
        self.offset+=self.batch
        speech_features = []
        input_length = []
        y1 = []
        label_length1 = []
        max_input = 0
        max_label1 = 0
        for i in sample:
            wp, txt = i.strip().split('\t')
            txt=txt.replace(' ','')
            try:
                data = self.speech_featurizer.load_wav(wp)
            except:
                print('{} load data failed,skip'.format(wp))
                continue
            if len(data) < 400:
                continue
            elif len(data) > self.speech_featurizer.sample_rate *  self.speech_config['wav_max_duration']:
                print('{} duration out of wav_max_duration({}) ,skip'.format(wp,self.speech_config['wav_max_duration']))
                continue
            if self.speech_config['only_chinese']:
                txt= self.only_chinese(txt)
            if self.speech_config['use_mel_layer']:
                speech_feature = data / np.abs(data).max()
                speech_feature = np.expand_dims(speech_feature, -1)
                in_len = len(speech_feature) // (
                        self.speech_config['reduction_factor'] * (self.speech_featurizer.sample_rate / 1000) *
                        self.speech_config['stride_ms'])
            else:
                speech_feature = self.speech_featurizer.extract(data)
                in_len = int(speech_feature.shape[0] // self.speech_config['reduction_factor'])
            max_input = max(max_input, speech_feature.shape[0])

            py = self.text_to_vocab(txt)
            if not self.check_valid(py, self.text_featurizer.vocab_array):
                print(' {} txt pinyin {} not all in tokens,skip'.format(txt,py))
                continue
            text_feature = self.text_featurizer.extract(py)

            if in_len < len(text_feature):
                print('{} feature length < pinyin length,skip'.format(wp))
                continue
            max_input = max(max_input, len(speech_feature))
            max_label1 = max(max_label1, len(text_feature))
            speech_features.append(speech_feature)
            input_length.append(in_len)
            y1.append(np.array(text_feature))
            label_length1.append(len(text_feature))

        if self.speech_config['use_mel_layer']:
            speech_features = self.speech_featurizer.pad_signal(speech_features, max_input)

        else:
            for i in range(len(speech_features)):

                if speech_features[i].shape[0] < max_input:
                    pad = np.ones([max_input - speech_features[i].shape[0], speech_features[i].shape[1],
                                   speech_features[i].shape[2]]) * speech_features[i].min()
                    speech_features[i] = np.vstack((speech_features[i], pad))

        for i in range(len(y1)):
            if y1[i].shape[0] < max_label1:
                pad = np.ones(max_label1 - y1[i].shape[0]) * self.text_featurizer.pad
                y1[i] = np.hstack((y1[i], pad))

        x = np.array(speech_features, 'float32')
        y1 = np.array(y1, 'int32')

        input_length = np.array(input_length, 'int32')
        label_length1 = np.array(label_length1, 'int32')

        return x, input_length, y1, label_length1
    def check_valid(self,txt,vocab_list):
        if len(txt)==0:
            return False
        for n in txt:
            if n in vocab_list:
                pass
            else:
                return False
        return True
    def GuidedAttentionMatrix(self, N, T, g=0.2):
        W = np.zeros((N, T), dtype=np.float32)
        for n in range(N):
            for t in range(T):
                W[n, t] = 1 - np.exp(-(t / float(T) - n / float(N)) ** 2 / (2 * g * g))
        return W

    def guided_attention(self, input_length, targets_length, inputs_shape, mel_target_shape):
        att_targets = []
        for i, j in zip(input_length, targets_length):
            i = int(i)
            step = int(j)
            pad = np.ones([inputs_shape, mel_target_shape]) * -1.
            pad[i:, :step] = 1
            att_target = self.GuidedAttentionMatrix(i, step, 0.2)
            pad[:att_target.shape[0], :att_target.shape[1]] = att_target
            att_targets.append(pad)
        att_targets = np.array(att_targets)

        return att_targets.astype('float32')
    def generate(self, train=True):

        if train:
            batch=self.batch if self.augment.available() else self.batch*2
            indexs = np.argsort(self.pick_index)[:batch]
            indexs = random.sample(indexs.tolist(), batch//2)
            sample = [self.train_list[i] for i in indexs]
            for i in indexs:
                self.pick_index[int(i)] += 1
            self.epochs =1+ int(np.mean(self.pick_index))
        else:
            sample = random.sample(self.test_list, self.batch)
        speech_features = []
        input_length = []
        y1 = []
        label_length1 = []

        max_input = 0
        max_label1 = 0
        for i in sample:
            wp, txt = i.strip().split('\t')
            try:
                data = self.speech_featurizer.load_wav(wp)
            except:
                print('{} load data failed,skip'.format(wp))
                continue
            if len(data) < 400:
                continue
            elif len(data) > self.speech_featurizer.sample_rate * self.speech_config['wav_max_duration']:
                print('{} duration out of wav_max_duration({}),skip'.format(wp, self.speech_config['wav_max_duration']))
                continue
            if self.speech_config['only_chinese']:
                txt= self.only_chinese(txt)
            if self.speech_config['use_mel_layer']:
                speech_feature = data / np.abs(data).max()
                speech_feature = np.expand_dims(speech_feature, -1)
                in_len = len(speech_feature) // (
                        self.speech_config['reduction_factor'] * (self.speech_featurizer.sample_rate / 1000) *
                        self.speech_config['stride_ms'])
            else:
                speech_feature = self.speech_featurizer.extract(data)
                in_len = int(speech_feature.shape[0] // self.speech_config['reduction_factor'])


            py = self.text_to_vocab(txt)
            if not self.check_valid(py,self.text_featurizer.vocab_array):
                print(' {} txt pinyin {} not all in tokens,continue'.format(txt, py))
                continue
            text_feature = self.text_featurizer.extract(py)

            if in_len < len(text_feature):
                print('{} feature length < pinyin length,continue'.format(wp))
                continue
            max_input = max(max_input,len(speech_feature))
            max_label1 = max(max_label1, len(text_feature))
            speech_features.append(speech_feature)
            input_length.append(in_len)
            y1.append(np.array(text_feature))
            label_length1.append(len(text_feature))
        if train and self.augment.available():
            for i in sample:
                wp, txt = i.strip().split('\t')
                try:
                    data = self.speech_featurizer.load_wav(wp)
                except:
                    continue
                if len(data) < 400:
                    continue
                elif len(data) > self.speech_featurizer.sample_rate *  self.speech_config['wav_max_duration']:
                    continue
                data = self.augment.process(data)
                if self.speech_config['only_chinese']:
                    txt = self.only_chinese(txt)
                if self.speech_config['use_mel_layer']:
                    speech_feature = data / np.abs(data).max()
                    speech_feature = np.expand_dims(speech_feature, -1)
                    in_len = len(speech_feature) // (
                            self.speech_config['reduction_factor'] * (self.speech_featurizer.sample_rate / 1000) *
                            self.speech_config['stride_ms'])
                else:
                    speech_feature = self.speech_featurizer.extract(data)
                    in_len = int(speech_feature.shape[0] // self.speech_config['reduction_factor'])

                py = self.text_to_vocab(txt)
                if not self.check_valid(py, self.text_featurizer.vocab_array):
                    continue

                text_feature = self.text_featurizer.extract(py)


                if in_len < len(text_feature):
                    continue
                max_input = max(max_input, len(speech_feature))
                max_label1 = max(max_label1, len(text_feature))
                speech_features.append(speech_feature)

                input_length.append(in_len)
                y1.append(np.array(text_feature))
                label_length1.append(len(text_feature))

        if self.speech_config['use_mel_layer']:
            speech_features = self.speech_featurizer.pad_signal(speech_features, max_input)

        else:
            for i in range(len(speech_features)):

                if speech_features[i].shape[0] < max_input:
                    pad = np.ones([max_input - speech_features[i].shape[0], speech_features[i].shape[1],
                                   speech_features[i].shape[2]]) * speech_features[i].min()
                    speech_features[i] = np.vstack((speech_features[i], pad))

        for i in range(len(y1)):
            if y1[i].shape[0] < max_label1:
                pad = np.ones(max_label1 - y1[i].shape[0])*self.text_featurizer.pad
                y1[i] = np.hstack((y1[i], pad))

        x = np.array(speech_features, 'float32')
        y1 = np.array(y1, 'int32')

        input_length = np.array(input_length, 'int32')
        label_length1 = np.array(label_length1, 'int32')

        return x, input_length, y1, label_length1
    def generator(self,train=True):
        while 1:
            x,  input_length, labels, label_length=self.generate(train)
            if x.shape[0]==0:
                print('load data length zero,continue')
                continue
            if self.LAS:
                guide_matrix = self.guided_attention(input_length, label_length, np.max(input_length),
                                                     label_length.max())
                yield x, input_length, labels, label_length,guide_matrix
            else:
                yield x,  input_length, labels, label_length


