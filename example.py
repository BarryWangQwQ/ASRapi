'''
STEP1:

introduces asr_model_init (model initialisation unit) and asr (speech recognition module) from asrapi

从asrapi中引入asr_model_init（模型初始化单元）和asr（语音识别模块）
'''

from asrapi import asr_model_init, asr

'''
STEP2:

Speech recognition model initialization
Accepts two parameters.
1. CPU (default) / GPU
2. device number of the GPU (leave blank if CPU)

语音识别模型初始化
接受两个参数：
1.CPU(默认) / GPU
2.GPU的设备编号(如果是CPU则留空)
'''

asr_model_init('CPU')
# asr_model_init('GPU', 0)

'''
STEP3:

The asr speech recognition module accepts only one parameter: the path to the sound file.
Its return value is a set of Chinese pinyin (list type)

asr语音识别模块只接受一个参数：声音文件的路径。
其返回值是一组中文拼音（list类型）
'''

result = asr('C:/Users/starb/Desktop/ASRapi/record.wav')
print(result)

