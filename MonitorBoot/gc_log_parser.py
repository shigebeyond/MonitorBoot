import os
import re
from pyutilb import ts
from pyutilb.file import read_file
from pyutilb.strs import substr_before
from pyutilb.util import set_vars
from ExcelBoot.boot import Boot as EBoot

# ExcelBoot的步骤文件
excel_boot_yaml = __file__.replace("gc_log_parser.py", "eb-gcs2xlsx.yml")

'''
gc日志解析，主要用于识别频繁gc 或 gc效率不高
    -Xms20M -Xmx20M -Xmn10M -XX:SurvivorRatio=8 # 堆大小
    -verbose:gc -XX:+PrintGCDetails  -Xloggc:gc.log # gc日志 
    -XX:+HeapDumpOnOutOfMemoryError # oom时dump出堆快照，如java_pid30949.hprof
    -XX:MaxTenuringThreshold=1 -XX:+PrintTenuringDistribution # 晋升老年代的age阈值 
'''
class GcLogParser(object):

    def __init__(self, log_file):
        self.log_file = os.path.abspath(log_file)
        self.start_time = os.path.getctime(self.log_file)
        self.gcs = [] # 收集日志信息

    # 获得上一条年轻代或老年代的gc信息
    def last_gc(self, is_full):
        is_full = bool(is_full)
        for gc in reversed(self.gcs):
            if gc['is_full'] == is_full:
                return gc

        return None

    # 解析gc日志
    # :param log_file 日志文件路径
    def parse(self):
        txt = read_file(self.log_file)
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
        gens = []
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
                gens.append(data) # 记录解析结果
            # 1.2 去掉解析过的年代部分字符串
            line = line.replace(item, '')
            # print("剩余gc行: " + line)

        # 2 处理总的空间+时间
        # 如 0.089: [Full GC (Ergonomics)   4848K->4088K(5632K), , 0.0416957 secs]
        # 如 0.084: [GC (Allocation Failure)  3556K->2886K(5632K), 0.0039928 secs]
        line = line.replace(', ,', ',').replace(') ', '):')
        gc = self.parse_gen(line)
        gc['jvm_time'] = substr_before(line, ': [') # gc发生时vm运行了多少秒
        is_full = 'Full GC' in line
        # 计算两次gc之间的时间间隔
        lastgc = self.last_gc(is_full)
        if lastgc is None:
            # gc['interval'] = gc['jvm_time'] # 你不知道他是从啥时开始监控日志的，也不知道监控之前有没有gc过
            gc['interval'] = 0
        else:
            gc['interval'] = float(gc['jvm_time']) - float(lastgc['jvm_time'])
        gc['is_full'] = is_full
        # print("解析总年代: " + line + ", 结果为: " + str(gc))

        # 3 展平多个年代
        # gc['gens'] = gens
        self.flatten_gens(gc, gens)

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
            'before': float(mat.group(2)),
            'after': float(mat.group(3)),
            'total': float(mat.group(4)),
        }
        # 总的才有secs部分
        secs = mat.group(6)
        if secs is not None:
            data['cost_time'] = float(secs)
        return data

    def flatten_gens(self, gc, gens):
        '''
        展平一次gc中的多个年代的变更：二维变为一维
           二维: 年代的数组  [{'name': 'PSYoungGen', 'before': 1536.0, 'after': 0.0, 'total': 1536.0}, {'name': 'ParOldGen', 'before': 3312.0, 'after': 4088.0, 'total': 4096.0}, {'name': 'Metaspace', 'before': 3313.0, 'after': 3313.0, 'total': 1056768.0}]
           一维: 年代名作为key的前缀 {'PSYoungGen.before': 1536.0, 'PSYoungGen.after': 0.0, 'PSYoungGen.total': 1536.0, 'ParOldGen.before': 3312.0, 'ParOldGen.after': 4088.0, 'ParOldGen.total': 4096.0, 'Metaspace.before': 3313.0, 'Metaspace.after': 3313.0, 'Metaspace.total': 1056768.0}
        :param gc:
        :param gens:
        :return:
        '''
        for gen in gens:
            name = gen['name']
            del gen['name']
            for k, v in gen.items():
                key = name + '.' + k
                gc[key] = v

    def filter_gcs(self, is_full):
        # return [gc for gc in self.gcs if gc['is_full'] == is_full]
        ret = []
        for gc in self.gcs:
            if gc['is_full'] == is_full:
                gc = gc.copy()
                del gc['is_full']
                ret.append(gc)
        return ret

    # 获得full gc
    def full_gcs(self):
        return self.filter_gcs(True)

    # 获得minor gc
    def minor_gcs(self):
        return self.filter_gcs(False)

    def gcs2xlsx(self, filename_pref):
        '''
        导出gc信息
        :param filename_pref:
        :return:
        '''
        # excel文件名
        filename_pref = filename_pref or 'JvmGC'
        now = ts.now2str("%Y%m%d%H%M%S")
        file = f'{filename_pref}-{now}.xlsx'
        # 设置变量
        vars = {
            'file': file,
            'minor_gcs': self.minor_gcs(),
            'full_gcs': self.full_gcs(),
        }
        set_vars(vars)
        # 导出excel
        boot = EBoot()
        boot.run_1file(excel_boot_yaml)
        return file

if __name__ == '__main__':
    line = '0.084: [GC (Allocation Failure) [PSYoungGen: 1525K->512K(1536K)] 3556K->2886K(5632K), 0.0039928 secs] [Times: user=0.01 sys=0.00, real=0.00 secs]'
    line = '0.089: [Full GC (Ergonomics) [PSYoungGen: 1536K->0K(1536K)] [ParOldGen: 3312K->4088K(4096K)] 4848K->4088K(5632K), [Metaspace: 3313K->3313K(1056768K)], 0.0416957 secs] [Times: user=0.13 sys=0.00, real=0.04 secs]'
    parser = GcLogParser('../logs/gc2.log')
    # parser.parse_gc_line(line)
    parser.parse()
    for gc in parser.gcs:
        print(gc)
    parser.gcs2xlsx(None)