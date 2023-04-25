import asyncio
import time

import psutil
from pyutilb.cmd import run_command, cmd_output2dataframe, run_command_async
from pyutilb.log import log

'''
主要使用 pidstat 命令来统计进程或线程的cpu、内存、io等信息
https://www.cnblogs.com/storyawine/p/13332052.html
'''

# -------------------------------- 磁盘统计 -----------------------------------
# 通过 iostat -x 来获得磁盘读写信息，主要拿 %util 来识别磁盘io频率(一秒中有百分之多少的时间用于I/O操作)
async def get_disk_io_df():
    # 1 执行命令
    output = await run_command_async(f'iostat -x')
    '''Linux 5.10.60-amd64-desktop (shi-PC)    2023年04月24日  _x86_64_        (6 CPU)

avg-cpu:  %user   %nice %system %iowait  %steal   %idle
          23.07    0.09    5.70    0.07    0.00   71.07

Device            r/s     w/s     rkB/s     wkB/s   rrqm/s   wrqm/s  %rrqm  %wrqm r_await w_await aqu-sz rareq-sz wareq-sz  svctm  %util
sda              0.04    0.00      1.10      0.00     0.00     0.00   0.00   0.00   14.27    0.00   0.00    29.16     0.00   7.90   0.03
sdb              7.44   12.02    296.64    616.39     1.33    14.19  15.18  54.14    0.29    1.14   0.02    39.85    51.30   0.67   1.31'''
    # 2 将命令结果转为df
    return cmd_output2dataframe(output, 5)  # 干掉5行

# 获得最高磁盘io频率(一秒中有百分之多少的时间用于I/O操作)
async def max_disk_util():
    df = get_disk_io_df()
    return df['%util'].max()

# -------------------------------- 进程cpu统计 -----------------------------------
# 通过 pidstat 来获得进程的cpu统计信息，用于找到cpu多的进程
async def get_process_cpu_df():
    # 1 执行命令
    output = await run_command_async(f'pidstat')
    '''Linux 5.10.60-amd64-desktop (shi-PC)    2023年04月24日  _x86_64_        (6 CPU)

16时40分05秒   UID       PID    %usr %system  %guest   %wait    %CPU   CPU  Command
16时40分05秒     0         1    0.01    0.01    0.00    0.00    0.02     1  systemd
16时40分05秒     0         2    0.00    0.00    0.00    0.00    0.00     1  kthreadd'''
    # 2 将命令结果转为df
    return cmd_output2dataframe(output, 2)  # 干掉2行

# 将df按列排序
def order_df(df, by, asc):
    df[by] = df[by].apply(float) # 排序列要先转为数值
    return df.sort_values(by=by, ascending=asc) # 按列排序

# 获得cpu最忙的进程id
async def top_cpu_process():
    # 1 获得进程
    df = await get_process_cpu_df()
    print(df)
    # 2 按%CPU降序
    df = order_df(df, '%CPU', False)
    print(df)
    # 3 选择第一个
    row = dict(df.iloc[0])
    log.info(f"cpu最忙的进程为: {row}")
    return row
# -------------------------------- 进程mem统计 -----------------------------------
# 通过 pidstat -r 来获得进程的mem统计信息，用于找到mem多的进程
async def get_process_mem_df():
    # 1 执行命令
    output = await run_command_async(f'pidstat -r')
    '''Linux 5.10.60-amd64-desktop (shi-PC)    2023年04月24日  _x86_64_        (6 mem)

16时40分05秒   UID       PID    %usr %system  %guest   %wait    %mem   mem  Command
16时40分05秒     0         1    0.01    0.01    0.00    0.00    0.02     1  systemd
16时40分05秒     0         2    0.00    0.00    0.00    0.00    0.00     1  kthreadd'''
    # 2 将命令结果转为df
    return cmd_output2dataframe(output, 2)  # 干掉2行

# 获得mem最忙的进程id
async def top_mem_process():
    # 1 获得进程
    df = await get_process_mem_df()
    # 2 按%mem降序
    df = order_df(df, '%mem', False)
    # 3 选择第一个
    row = dict(df.iloc[0])
    log.info(f"mem最忙的进程为: {row}")
    return row

# -------------------------------- 进程io统计 -----------------------------------
# 通过 pidstat -d 来获得进程的io统计信息，用于找到io多的进程
async def get_process_io_df():
    # 1 执行命令
    output = await run_command_async(f'pidstat -d')
    '''Linux 5.10.60-amd64-desktop (shi-PC)    2023年04月24日  _x86_64_        (6 CPU)

16时09分10秒   UID       PID   kB_rd/s   kB_wr/s kB_ccwr/s iodelay  Command
16时09分11秒  1000       347      0.00      7.77      0.00       0  chrome
16时09分11秒     0       808     -1.00     -1.00     -1.00       1  jbd2/sdb4-8'''
    # 2 将命令结果转为df
    return cmd_output2dataframe(output, 2)  # 干掉2行

# 获得io最忙的进程id
async def top_io_process(is_read):
    # 1 获得进程
    df = await get_process_io_df()
    # 2 按读写速度降序
    if is_read:
        order_by = 'kB_rd/s'
        label = '读'
    else:
        order_by = 'kB_wr/s'
        label = '写'
    df = df.sort_values(by=order_by, ascending=False)
    # 3 选择第一个
    row = dict(df.iloc[0])
    log.info(f"io{label}最忙的进程为: {row}")
    return row

# -------------------------------- 线程处理 -----------------------------------
# 挑出cpu最忙的线程： 用 pidstat -t -p pid
async def top_cpu_thread(pid):
    # 1 获得线程
    df = await get_threads_df(pid)
    # 2 按cpu降序
    df = order_df(df, '%CPU', False)
    # 3 选择第一个
    # 取前2个: print(df.head(2))
    # 取第1个: df.iloc[0]
    row = dict(df.iloc[0])
    row['NID'] = hex(int(row['TID']))  # tid的16进制
    log.info(f"进程[{pid}]中cpu最忙的线程为: {row}")
    return row

# 通过 pidstat -t -p pid 来获得线程
async def get_threads_df(pid):
    # 1 执行命令
    output = await run_command_async(f'pidstat -t -p {pid}')
    '''Linux 5.10.60-amd64-desktop (shi-PC) 	2023年04月23日 	_x86_64_	(6 CPU)

11时28分27秒   UID      TGID       TID    %usr %system  %guest   %wait    %CPU   CPU  Command
11时28分27秒  1000      9702         -   19.37    0.50    0.00    0.00   19.87     0  java
11时28分27秒  1000         -      9702    0.00    0.00    0.00    0.00    0.00     0  |__java'''
    # 2 将命令结果转为df
    df = cmd_output2dataframe(output, 2) # 干掉2行
    # 3 删除第一行是进程而不是线程，如java且tid为-
    df = df.drop(0)
    # 4 过滤java中的业务线程: 通过构建 VM_THREAD 列来过滤
    # df['VM_THREAD'] = build_vm_thread_col(df)
    # df = df.loc[lambda x: x['VM_THREAD'] == False]
    # del df['VM_THREAD']
    return df

# 构建是否vm线程，非业务线程
def build_vm_thread_col(df):
    ret = []
    for i, row in df.iterrows():
        # 第一条是进程而不是线程，如java且tid为-，不要
        # 其他: vm线程不要
        val = row['TID'] == '-' \
              or is_vm_thread(row['Command'])
        ret.append(val)
    return ret

# 是否vm线程，非业务线程
features = 'GC Thread#,G1 Main Marker,G1 Conc#,G1 Refine#,G1 Young RemSet,VM Thread,Reference Handl,Finalizer,Signal Dispatch,Service Thread,C2 CompilerThre,C1 CompilerThre,Sweeper thread,VM Periodic Tas,Common-Cleaner,process reaper,GC Thread#,GC Thread#,GC Thread#,GC Thread#,GC Thread#,G1 Refine#,G1 Conc#,G1 Refine#,G1 Refine#'.split(',')
def is_vm_thread(thread_name):
    for f in features:
        if f in thread_name:
            return True
    return False

async def test():
    # df = await get_threads_df('5872')
    # df = await get_disk_io_df()
    # df = await get_process_io_df()
    # print(df)

    # io最忙的进程
    # await top_io_process(True)
    # p = await top_io_process(False)
    # cpu最忙的进程
    p = await top_cpu_process()
    pid = p['PID']
    # df = await get_threads_df(pid)
    # print(df)
    t = await top_cpu_thread(pid)

if __name__ == '__main__':
    asyncio.run(test())