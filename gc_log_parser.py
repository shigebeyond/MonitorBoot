# gc日志解析
import re

from pyutilb.file import read_file
from pyutilb.strs import substr_before

'''
gc日志解析，主要用于识别频繁gc 或 gc效率不高
    -Xms20M -Xmx20M -Xmn10M -XX:SurvivorRatio=8 # 堆大小
    -verbose:gc -XX:+PrintGCDetails  -Xloggc:gc.log # gc日志 
    -XX:+HeapDumpOnOutOfMemoryError # oom时dump出堆快照，如java_pid30949.hprof
    -XX:MaxTenuringThreshold=1 -XX:+PrintTenuringDistribution # 晋升老年代的age阈值 
'''
class GcLogParser(object):

    def __init__(self):
        # 日志文件
        self.log_file = None
        # 收集日志信息
        self.gcs = []

    # 获得上一条年轻代或老年代的gc信息
    def last_gc(self, is_full):
        is_full = bool(is_full)
        for gc in reversed(self.gcs):
            if gc['Sum']['is_full'] == is_full:
                return gc

        return None

    # 解析gc日志
    # :param log_file 日志文件路径
    def parse_gc_log(self, log_file):
        txt = read_file(log_file)
        for line in txt.splitlines():
            # 解析单行
            gc = self.parse_gc_line(line)

    def parse_gc_line(self, line):
        '''
        解析gc日志行, 其中 fullgc比gc多了[Perm:28671K->28635K(28672K)]
            0.084: [GC (Allocation Failure) [PSYoungGen: 1525K->512K(1536K)] 3556K->2886K(5632K), 0.0039928 secs] [Times: user=0.01 sys=0.00, real=0.00 secs]
            0.089: [Full GC (Ergonomics) [PSYoungGen: 1536K->0K(1536K)] [ParOldGen: 3312K->4088K(4096K)] 4848K->4088K(5632K), [Metaspace: 3313K->3313K(1056768K)], 0.0416957 secs] [Times: user=0.13 sys=0.00, real=0.04 secs]
        :param line:
        :return:
        '''
        if ': [' not in line:
            return None
        gc = {}
        # print("解析gc行: " + line)
        line = line.replace('--', '') # 特殊例子: 0.095: [GC (Allocation Failure) --[PSYoungGen: 1520K->1520K(1536K)] 4784K->5608K(5632K), 0.0099458 secs] [Times: user=0.03 sys=0.00, real=0.01 secs]
        # 1 处理几个年代的空间+时间
        items = re.findall('\[[^\[^\]]+\]', line)
        for item in items:
            # 1.1 解析单个年代
            if item.startswith('[Times:'): # 忽略 [Times: user=0.13 sys=0.00, real=0.04 secs]
                # print("忽略非年代: " + item)
                pass
            else: # 解析单个年代
                data = self.parse_gen(item)
                if data is None:
                    raise Exception("解析年代失败: " + item)
                # print("解析年代: " + item + ", 结果为: " + str(data))
                gc[data['name']] = data # 记录解析结果
            # 1.2 去掉解析过的年代部分字符串
            line = line.replace(item, '')
            # print("剩余gc行: " + line)
        # 2 处理总的空间+时间
        # 如 0.089: [Full GC (Ergonomics)   4848K->4088K(5632K), , 0.0416957 secs]
        # 如 0.084: [GC (Allocation Failure)  3556K->2886K(5632K), 0.0039928 secs]
        line = line.replace(', ,', ',').replace(') ', '):')
        data = self.parse_gen(line)
        data['jvm_time'] = substr_before(line, ': [') # gc发生时vm运行了多少秒
        data['is_full'] = 'Full GC' in line
        # print("解析总年代: " + line + ", 结果为: " + str(data))
        gc['Sum'] = data  # 记录解析结果
        # print(gc)
        if gc is not None:
            self.gcs.append(gc)
        return gc

    # 解析一代: 如 [PSYoungGen: 1536K->0K(1536K)]
    def parse_gen(self, gen):
        mat = re.search('\[([^:]+): +(\d+)K->(\d+)K\((\d+)K\)(, ([\d\.]+) secs)?', gen)
        if mat == None:
            return None
        data = {
            'name': mat.group(1),
            'before': mat.group(2),
            'after': mat.group(3),
            'total': mat.group(4),
        }
        # 总的才有secs部分
        secs = mat.group(6)
        if secs is not None:
            data['cost_time'] = secs
        return data

if __name__ == '__main__':
    line = '0.084: [GC (Allocation Failure) [PSYoungGen: 1525K->512K(1536K)] 3556K->2886K(5632K), 0.0039928 secs] [Times: user=0.01 sys=0.00, real=0.00 secs]'
    # line = '0.089: [Full GC (Ergonomics) [PSYoungGen: 1536K->0K(1536K)] [ParOldGen: 3312K->4088K(4096K)] 4848K->4088K(5632K), [Metaspace: 3313K->3313K(1056768K)], 0.0416957 secs] [Times: user=0.13 sys=0.00, real=0.04 secs]'
    parser = GcLogParser()
    # parser.parse_gc_line(line)
    parser.parse_gc_log('logs/gc2.log')
    for gc in parser.gcs:
        print(gc)