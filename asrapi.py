from utils.user_config import UserConfig
from AMmodel.model import AM
from LMmodel.trm_lm import LM
import pypinyin
from pypinyin import lazy_pinyin
import os

from getaudio import get_audio


class ASR:
    def __init__(self, am_config, lm_config):

        self.am = AM(am_config)
        self.am.load_model(False)

        self.lm = LM(lm_config)
        self.lm.load_model(False)

    def decode_am_result(self, result):
        return self.am.decode_result(result)

    def stt(self, wav_path):

        am_result = self.am.predict(wav_path)
        if self.am.model_type == 'Transducer':
            am_result = self.decode_am_result(am_result[1:-1])
            lm_result = self.lm.predict(am_result)
            lm_result = self.lm.decode(lm_result[0].numpy(), self.lm.word_featurizer)
        else:
            am_result = self.decode_am_result(am_result[0])
            lm_result = self.lm.predict(am_result)
            lm_result = self.lm.decode(lm_result[0].numpy(), self.lm.word_featurizer)
        return am_result, lm_result

    def am_test(self, wav_path):
        # am_result is token id
        am_result = self.am.predict(wav_path)
        # token to vocab
        if self.am.model_type == 'Transducer':
            am_result = self.decode_am_result(am_result[1:-1])
        else:
            am_result = self.decode_am_result(am_result[0])
        return am_result

    def lm_test(self, txt):
        py = pypinyin.pinyin(txt)
        input_py = [i[0] for i in py]
        # now lm_result is token id
        lm_result = self.lm.predict(input_py)
        # token to vocab
        lm_result = self.lm.decode(lm_result[0].numpy(), self.lm.word_featurizer)
        return lm_result


def asr_model_init(device: str, code=-1):
    global asr_obj
    if device == 'CPU' and code == -1:
        # USE CPU:
        os.environ['CUDA_VISIBLE_DEVICES'] = '-1'
    elif device == 'GPU' and code >= 0:
        # USE one GPU:
        os.environ['CUDA_VISIBLE_DEVICES'] = str(code)
        # os.environ['CUDA_VISIBLE_DEVICES'] = '0'
        # limit cpu to 1 core:
        # tf.config.threading.set_inter_op_parallelism_threads(1)
        # tf.config.threading.set_intra_op_parallelism_threads(1)
    else:
        os.environ['CUDA_VISIBLE_DEVICES'] = '-1'

    am_config = UserConfig('./weight/AM/am_data.yml', './weight/AM/conformerM.yml')
    lm_config = UserConfig('./weight/LM/lm_data.yml', './weight/LM/transformer.yml')
    asr_obj = ASR(am_config, lm_config)

    asr_obj.stt('./init/init_file')
    #print('ASR 模型初始化成功')


def asr(data):
    try:
        zhuyin, character = asr_obj.stt(data)
        pinyin = lazy_pinyin(character)
        return pinyin
    except:
        print('声音读取失败,请重试.')
        return None

'''
if __name__ == '__main__':
    # USE CPU:
    os.environ['CUDA_VISIBLE_DEVICES'] = '-1'
    # USE one GPU:
    # os.environ['CUDA_VISIBLE_DEVICES'] = '0'
    # limit cpu to 1 core:
    # tf.config.threading.set_inter_op_parallelism_threads(1)
    # tf.config.threading.set_intra_op_parallelism_threads(1)

    am_config = UserConfig('./weight/AM/am_data.yml', './weight/AM/conformerM.yml')
    lm_config = UserConfig('./weight/LM/lm_data.yml', './weight/LM/transformer.yml')
    asr = ASR(am_config, lm_config)

    asr.stt('./init/init_file')
    print('模型初始化成功')

    while True:
        data = input('请输入声音(.wav)的路径：')
        # get_audio('./init/record')
        # data = './init/record'
        try:
            zhuyin, character = asr.stt(data)
            pinyin = lazy_pinyin(character)
            print('预测的汉语拼音结果为：', zhuyin)
            print('可能的汉字结果为：', character)
            print('输出可供后续处理的字符集：', pinyin)
        except:
            print('声音读取失败,请重试.')
            pass
'''
