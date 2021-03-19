English:

Quick start.

Step 1: In the project root directory execute
"pip install -r requirements.txt"
to install the dependencies.

Step 2: In the project root directory, edit
"example.py" and
Modify the third code: ASR's sound file recognition path (sound files are only supported for WAV)

Step 3: In the project root directory, execute
"python example.py"
to see the results of the sample program

Possible bug：
1. numpy has issued a new version that conflicts with tensorflow.
Solution: switch to version 0.18.5 and set user mode to be compatible.
2. If you have librosa in version 0.7, you must pair it with 0.48.0 of numba.

Related statements：

ASR api by Meownic Team - Barry Wang
The Meownic Team has the right to interpret this code.
This code is for learning and non-commercial use only. If you need to use this code for commercial purposes, please send an email to StarBarry777@qq.com and tell us what you are actually using it for.

Note: The code and API are for non-commercial or learning use only.



中文：

快速上手：

第一步：在项目根目录下执行
“pip install -r requirements.txt”
来安装相关依赖

第二步：在项目根目录下编辑
“example.py”
修改第三项代码：ASR的声音文件识别路径（声音文件仅支持WAV）

第三步：在项目根目录下执行
“python example.py”
来查看样例程序结果

可能存在的BUG：
1.numpy发的新版本跟tensorflow有冲突。
解决方法：调到0.18.5版本设置user模式就可以兼容了
2.如果有librosa在0.7版本必须搭配0.48.0的numba。

相关声明：

ASR api 由 Meownic Team 的 BarryWang 制作
Meownic Team 拥有对该代码的解释权
此代码仅限学习和非商业用途使用，如果您需要使用此代码用于商业领域，请发送一封电子邮件到：StarBarry777@qq.com，并告诉我们您的实际用途。

注意：代码和API仅供非商业领域或学习使用。




BarryWang 2021/3/5

关注 + follow -> api.meownic.com
