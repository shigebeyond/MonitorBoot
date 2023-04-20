import re

from pyutilb.file import read_file
from pyutilb.strs import substr_before

'''
线程日志解析，主要用于识别线程id，然后导出线程栈
日志需包含`tid=110`，表示输出线程id
'''
class ThreadLogParser(object):

    def __init__(self):
        # 收集线程id信息
        self.tids = []

    # 解析thread日志
    # :param log_file 日志文件路径
    def parse_thread_log(self, log_file):
        txt = read_file(log_file)
        for line in txt.splitlines():
            # 解析单行
            tid = self.parse_thread_line(line)

    def parse_thread_line(self, line):
        mat = re.search('tid=(\d+)', line)
        if mat is None:
            return None

        tid = mat.group(1)
        self.tids.append(tid)
        return tid

if __name__ == '__main__':
    line = 'xxx tid=110'
    parser = ThreadLogParser()
    parser.parse_thread_line(line)
    print(parser.tids)