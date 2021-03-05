import pyaudio
import wave


def get_audio(filepath: str, record_seconds=3, rate=16000, channels=1):
    CHUNK = 256
    FORMAT = pyaudio.paInt16
    CHANNELS = channels  # 声道数
    RATE = rate  # 采样率
    RECORD_SECONDS = record_seconds
    WAVE_OUTPUT_FILENAME = filepath
    p = pyaudio.PyAudio()

    stream = p.open(format=FORMAT,
                    channels=CHANNELS,
                    rate=RATE,
                    input=True,
                    frames_per_buffer=CHUNK)

    print('\n开始录音：请在', str(record_seconds), '秒内输入声音\n')
    frames = []
    for i in range(0, int(RATE / CHUNK * RECORD_SECONDS)):
        data = stream.read(CHUNK)
        frames.append(data)
    print("\n录音结束\n")

    stream.stop_stream()
    stream.close()
    p.terminate()

    wf = wave.open(WAVE_OUTPUT_FILENAME, 'wb')
    wf.setnchannels(CHANNELS)
    wf.setsampwidth(p.get_sample_size(FORMAT))
    wf.setframerate(RATE)
    wf.writeframes(b''.join(frames))
    wf.close()
