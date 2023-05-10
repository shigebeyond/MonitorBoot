[GitHub](https://github.com/shigebeyond/MonitorBoot) | [Gitee](https://gitee.com/shigebeyond/MonitorBoot)

# MonitorBoot - yaml驱动linux系统监控

## 概述
框架通过编写简单的yaml, 就可以实现复杂的性能监控与告警处理, 如告警/dump jvm堆快照/dump jvm线程栈/提取变量/打印变量等，极大的简化了伙伴编写监控脚本的工作量与工作难度，大幅提高人效；

框架通过支持3类17个指标的告警，适用于广泛的监控与告警场景。

框架提供`include`机制，用来加载并执行其他的步骤yaml，一方面是功能解耦，方便分工，一方面是功能复用，提高效率与质量，从而推进监控脚本整体的工程化。

底层实现使用协程，高性能

## 作用
1. 可做系统监控与报警
2. 支持解析gc log，借以监控gc耗时或频率
3. 配合Locust性能测试框架，做性能监控与报表，以弥补Locust监控功能的缺失

## 特性
1. 支持通过yaml来配置执行的步骤，简化了监控脚本开发:
每个步骤可以有多个动作，但单个步骤中动作名不能相同（yaml语法要求）;
动作代表一种监控操作，如schedule/alert/send_email/dump_sys_csv等等;
2. 支持用`include`动作引用其他的yaml配置文件，以便解耦与复用;
3. 支持用`schedule`动作来实现定时处理;
4. 支持用`monitor_gc_log`动作来订阅与解析gc log，以便分析与监控gc耗时或频率;
5. 支持3类17个指标的告警: 1 系统性能指标 2 进程性能指标 3 gc耗时或频率指标
6. 支持导出多种性能报告文件，如jvm堆快照/jvm线程栈/gc记录的xlsx/所有进程信息的xlsx/有时序的系统性能指标的csv/有时序的进程性能指标的csv
7. 定时处理与异步执行命令都是使用协程来实现，高性能。

## 同类yaml驱动的框架
[HttpBoot](https://github.com/shigebeyond/HttpBoot)
[SeleniumBoot](https://github.com/shigebeyond/SeleniumBoot)
[AppiumBoot](https://github.com/shigebeyond/AppiumBoot)
[MiniumBoot](https://github.com/shigebeyond/MiniumBoot)
[ExcelBoot](https://github.com/shigebeyond/ExcelBoot)

## todo
1. 支持更多的动作

## 安装
```
sudo apt install sysstat
pip3 install MonitorBoot
```

安装后会生成命令`MonitorBoot`;

注： 对于深度deepin-linux系统，生成的命令放在目录`~/.local/bin`，建议将该目录添加到环境变量`PATH`中，如
```
export PATH="$PATH:/home/shi/.local/bin"
```

## 使用
1. 执行
```
# 1 执行单个文件
MonitorBoot 步骤配置文件.yml

# 2 执行多个文件
MonitorBoot 步骤配置文件1.yml 步骤配置文件2.yml ...

# 3 执行单个目录, 即执行该目录下所有的yml文件
MonitorBoot 步骤配置目录

# 4 执行单个目录下的指定模式的文件
MonitorBoot 步骤配置目录/step-*.yml
```

2. `-t`指定运行时间，可以用来配合在Locust的压测时间内同步监控系统性能。
```
# 指定运行时间为600秒(10分钟)
MonitorBoot 步骤配置文件.yml -t 600
```

## 步骤配置文件
用于指定多个步骤, 示例见源码 [example](https://github.com/shigebeyond/MonitorBoot/tree/main/example) 目录下的文件;

顶级的元素是步骤;

每个步骤里有多个动作(如schedule/alert/send_email/dump_sys_csv)，如果动作有重名，就另外新开一个步骤写动作，这是由yaml语法限制导致的，但不影响步骤执行。

## 配置详解
支持通过yaml来配置执行的步骤;

每个步骤可以有多个动作，但单个步骤中动作名不能相同（yaml语法要求）;

动作代表一种监控操作，如schedule/alert/send_email/dump_sys_csv等等;

下面详细介绍每个动作:
1. sleep: 线程睡眠; 
```yaml
sleep: 2 # 线程睡眠2秒
```

2. print: 打印, 支持输出变量/函数; 
```yaml
# 调试打印
print: "总申请数=${dyn_data.total_apply}, 剩余份数=${dyn_data.quantity_remain}"
```

变量格式:
```
$msg 一级变量, 以$为前缀
${data.msg} 多级变量, 用 ${ 与 } 包含
```

函数格式:
```
${random_str(6)} 支持调用函数，目前仅支持以下几个函数: random_str/random_int/random_element/incr
```

函数罗列:
```
now(): 当前时间字符串
random_str(n): 随机字符串，参数n是字符个数
random_int(n): 随机数字，参数n是数字个数
random_element(var): 从list中随机挑选一个元素，参数var是list类型的变量名
incr(key): 自增值，从1开始，参数key表示不同的自增值，不同key会独立自增
```

3. include: 包含其他步骤文件，如记录公共的步骤，或记录配置数据(如用户名密码); 
```yaml
include: part-common.yml
```

4. set_vars: 设置变量; 
```yaml
set_vars:
  name: shi
  password: 123456
  birthday: 5-27
```

5. print_vars: 打印所有变量; 
```yaml
print_vars:
```

6. config_email: 配置邮件信息
```yaml
- config_email:
      host: smtp.qq.com
      password: $emailpass
      from_name: MonitorBoot
      from_email: aaa@qq.com
      to_name: shigebeyond # 可选，
      to_email: bbb@qq.com
```

7. send_email: 发送邮件
```yaml
- send_email:
    title: hello
    msg: hello world
```

8. schedule: 定时处理，就是每隔指定秒数就执行下子步骤
```yaml
# 定时处理
- schedule(5): # 每隔5秒 
    # 执行子步骤
    - print: '每隔5s触发: ${now()}'
```

9. tail: 订阅文件中最新增加的行，其中变量 tail_line 记录最新增加的行
```yaml
- tail(/home/shi/test.log): # 订阅文件 /home/shi/test.log   
    # 执行子步骤，能读到变量 tail_line
    - print: '最新行: $tail_line'
```

10. alert: 告警处理动作，他会逐个执行告警条件，如果满足条件则发生告警并调用`when_alert`注册的子步骤
```yaml
- alert: # 告警
    # 告警条件
    # 1 系统的性能指标相关的条件
    - sys.cpu_percent >= 90 # cpu使用率 >= 90%
    - sys.mem_used >= 1024M # 已使用内存 >= 1024M
    - sys.mem_free <= 1024M # 剩余内存 <= 1024M
    - sys.mem_percent >= 90 # 内存使用率 >= 90%
    - sys.disk_percent >= 90 # 磁盘使用率 >= 90%
    - sys.disk_read >= 10M # 读速率 >= 10M
    - sys.disk_write >= 10M # 写速率 >= 10M
    - sys.net_recv >= 10M # 接收速率 >= 10M
    - sys.net_sent >= 10M # 发送速率 >= 10M

    # 2 监控的进程的性能指标相关的条件，仅在有监控进程的情况下使用
    - proc.cpu_percent >= 90 # cpu的使用频率 >= 90%
    - proc.mem_used >= 1024M # 已用内存 >= 1024M
    - proc.mem_percent >= 1024M # 内存使用率 >= 1024M
    - proc.disk_read >= 10M # 读速率 >= 10M
    - proc.disk_write >= 10M # 写速率 >= 10M
  
    # 3 gc指标相关的条件，仅在有监控gc log的情况下使用
    - ygc.costtime > 5 # minor gc耗时 > 5s
    - fgc.costtime > 5
    - fgc.interval < 10 # full gc间隔时间 < 10s
```

限制告警的处理频率，以防止告警通知(发邮件)太频繁
```yaml
- alert(60): # 60秒内不处理同条件的告警，也就是说： 在60秒内如果发生多个同条件的告警，只处理第一个告警
    - fgc.interval < 10
- alert: # 默认是600秒内不处理同条件的告警
    - fgc.interval < 10
```

告警条件格式: `指标 操作符 对比值`，其中指标与操作符有：

10.1 系统的性能指标

| 指标名 | 含义 |
| ------------ | ------------ |
| sys.cpu_percent | cpu使用率 |
| sys.mem_used | 已使用内存 |
| sys.mem_free | 剩余内存 |
| sys.mem_percent | 内存使用率 |
| sys.disk_percent | 磁盘使用率 |
| sys.disk_read | 读速率 |
| sys.disk_write | 写速率 |
| sys.net_recv | 接收速率 |
| sys.net_sent | 发送速率 |

10.2 进程的性能指标

| 指标名 | 含义 |
| ------------ | ------------ |
| proc.cpu_percent | cpu的使用频率 |
| proc.mem_used | 已用内存 |
| proc.mem_percent | 内存使用率 |
| proc.disk_read | 读速率 |
| proc.disk_write | 写速率 |

10.3 gc记录的耗时与频率指标

| 指标名 | 含义 |
| ------------ | ------------ |
| ygc.costtime | minor gc耗时 |
| ygc.interval | minor gc间隔时间 |
| fgc.costtime | full gc耗时 |
| fgc.interval | full gc间隔时间 |

10.4 操作符

| 操作符 | 含义 |
| ------------ | ------------ |
| `=` | 相同 |
| `>` | 大于 |
| `<` | 小于 |
| `>=` | 大于等于 |
| `<=` | 小于等于 |

11. when_alert: 记录当发生告警要调用的子步骤
```yaml
- when_alert: # 发生告警时要执行以下子步骤
    # 子步骤
    - send_alert_email: # 发告警邮件
```

12. send_alert_email: 发告警邮件
```yaml
- send_alert_email: # 发告警邮件
```
发送的邮件如下:
![](img/alert_email.png)

13. monitor_pid: 监控进程的pid，其实现就是定时调用 grep_pid 动作
```yaml
# 监控进程的pid
- monitor_pid:
    grep: java | visualvm | org.netbeans.Main # 用 `ps aux | grep` 搜索进程时要搜索的关键字，支持多个，用|分割
    interval: 10 # 定时检查的时间间隔，可省，默认10秒
    when_no_run: # 没运行时执行以下步骤
      - exec: nohup jvisualvm & # 重启程序
```

14. grep_pid: 搜索进程的pid
```yaml
grep_pid: java | visualvm | org.netbeans.Main # 用 `ps aux | grep` 搜索进程时要搜索的关键字，支持多个，用|分割
```

15. monitor_gc_log: 监控gc日志
```yaml
# 监控gc日志
- monitor_gc_log(/home/shi/code/testing/kt-test/gc.log):
    # 当有新的gc记录时，执行以下子步骤
    - when_alert: # 发生告警时要执行以下步骤
        - send_alert_email: # 发告警邮件
    - alert: # 告警
          - ygc.costtime > 5 # gc耗时 > 5s
          - fgc.costtime > 5
          - fgc.interval < 10 # gc间隔时间 < 10s
```

16. dump_jvm_heap: 导出jvm堆快照，导出文件名如`JvmHeap-20230505164656.hprof`
```yaml
- dump_jvm_heap: # dump jvm堆快照(如果你监控了jvm进程)
```

17. dump_jvm_thread: 导出jvm线程栈，导出文件名如`JvmThread-20230505164657.tdump`
```yaml
- dump_jvm_thread: # dump jvm线程栈(如果你监控了jvm进程)
```

18. dump_jvm_gcs_xlsx: 导出gc记录的xlsx，导出文件名如`JvmGC-20230505164657.xlsx`
```yaml
- dump_jvm_gcs_xlsx: # dump gc记录
- dump_jvm_gcs_xlsx: # dump gc记录
    #bins: 8 # 分区数，bins与interval参数是二选一
    interval: 10 # 分区的时间间隔，单位秒，bins与interval参数是二选一
```

文件内容如下:
![](img/all_gc.png)
![](img/minor_gc.png)
![](img/full_gc.png)
![](img/all_bins.png)
![](img/minor_bins.png)
![](img/full_bins.png)

19. dump_all_proc_xlsx: 导出所有进程信息的xlsx，导出文件名如`ProcStat-20230508083721.xlsx`
```yaml
- dump_all_proc_xlsx: # dump所有进程
```

文件内容如下:
![](img/dir.png)
![](img/disk_io_stat.png)
![](img/process_cpu_stat.png)
![](img/process_io_stat.png)
![](img/process_mem_stat.png)
![](img/threads_of_pid_7558.png)
最后一个为指定进程的线程信息，最后一列`nid`为线程id的16进制，拿着`nid`可在导出的jvm线程栈文件去找对应线程信息

20. dump_sys_csv: 将系统性能指标导出到csv中，导出文件名如`Sys-2023-05-08.csv`，性能指标有：cpu%/s, mem%/s, mem_used(MB), disk_read(MB/s), disk_write(MB/s), net_sent(MB/s), net_recv(MB/s)；一般配合`schedule`动作来使用
```yaml
- dump_sys_csv:
- dump_sys_csv: 导出的csv文件前缀
```

文件内容如下：
![](img/dump_sys.png)

21. dump_1proc_csv: 将当前被监控的进程的性能指标导出到csv中，导出文件名如`Proc-java:org.netbeans.Main[18733]-2023-05-08.csv`，性能指标有：cpu%/s, mem_used(MB), mem%, status；一般配合`schedule`动作来使用
```yaml
- dump_1proc_csv:
- dump_1proc_csv: 导出的csv文件前缀
```

文件内容如下：
![](img/dump_proc.png)

22. compare_gc_logs: 对比多个gc log，并将对比结果存到excel中，导出文件名如`对比gc-20230509170722.xlsx`
```yaml
# 对比多个gc log，并将对比结果存到excel中
- compare_gc_logs:
      logs: # 要对比的gc log文件，可以是dict或list
#        - /home/shi/code/testing/kt-test/gc2.log
#        - /home/shi/code/testing/kt-test/gc5.log
        优化前: /home/shi/code/testing/kt-test/gc2.log
        优化后: /home/shi/code/testing/kt-test/gc5.log
      interval: 30 # 分区的时间间隔，单位秒
      filename_pref: 对比gc # 生成的结果excel文件前缀，可省，默认为JvmGCCompare
```

文件内容如下，可以很直观的看到2个gc的优劣：
![](img/compare_gc_costtime.png)
![](img/compare_gc_count.png)
![](img/compare_gc1.png)
![](img/compare_gc2.png)
![](img/compare_bins1.png)
![](img/compare_bins2.png)

23. exec: 执行命令
```yaml
exec: ls
```

24. stop_after: 在指定秒数后结束
```yaml
stop_after: 600 # 600秒(10分钟)后结束 MonitorBoot 进程
```

25. stop_at: 在指定时间结束
```yaml
stop_at: 2022-7-6 13:44:10 # 在 2022-7-6 13:44:10 时结束 MonitorBoot 进程
```

## 案例介绍
### 1 监控系统性能
[监控脚本](example/dump_sys.yml)
1. 定时监控系统的性能指标，并将指标值写入到csv中；
2. 性能指标有：cpu%/s, mem%/s, mem_used(MB), disk_read(MB/s), disk_write(MB/s), net_sent(MB/s), net_recv(MB/s)

```
# example/dump_sys.yml

# 配置邮件账号
- config_email:
  host: smtp.qq.com
  password: $emailpass
  from_name: MonitorBoot
  from_email: ???@qq.com
  to_name: ???
  to_email: ???@qq.com

# 定时做系统告警
- schedule(10):
    - when_alert: # 发生告警时要执行以下步骤
        - send_alert_email: # 发告警邮件
        - dump_all_proc_xlsx: # dump所有进程
    - alert: # 告警
      # 告警条件
        - sys.mem_free <= 1024M # 剩余内存 <= 1024M
        - cpu_percent >= 90 # cpu使用率 >= 90%
      # - disk_percent >= 90 # 磁盘使用率 >= 90%
```

[运行视频](https://www.zhihu.com/zvideo/1637876392099291137)

### 2 监控进程性能
[监控脚本](example/dump_process.yml)
1. 定时监控指定进程(jvisualvm)的性能指标，并将指标值写入到csv中；
2. 性能指标有：cpu%/s, mem_used(MB), mem%, status
```
# example/dump_process.yml

# 监控进程的pid，当进程不存在时重启程序
- monitor_pid:
  grep: java | visualvm | org.netbeans.Main # 用 `ps aux | grep` 搜索进程时要搜索的关键字，支持多个，用|分割
  interval: 5 # 定时检查的时间间隔，可省，默认10秒
  when_no_run: # 没运行时执行以下步骤
  - exec: nohup jvisualvm & # 重启程序

# 定时导出进程信息
- schedule(5):
    - dump_1proc_csv: # dump当前监控的进程
```

[运行视频](https://www.zhihu.com/zvideo/1637878398616952833)

### 3 监控进程存活
[监控脚本](example/monitor_and_restart_process.yml)
1. 定时监控进程(jvisualvm)的存活状态
2. 如果进程未运行，则重启jvisualvm
```
# example/monitor_and_restart_process.yml

# 监控进程的pid，当进程不存在时重启程序
- monitor_pid:
  grep: java | visualvm | org.netbeans.Main # 用 `ps aux | grep` 搜索进程时要搜索的关键字，支持多个，用|分割
  interval: 10 # 定时检查的时间间隔，可省，默认10秒
  when_no_run: # 没运行时执行以下步骤
  - exec: nohup jvisualvm & # 重启程序
```

[运行视频](https://www.zhihu.com/zvideo/1637875128171290626)

### 4 监控系统并报警
[报警脚本](example/alert_sys.yml)
1. 定时做系统性能指标检查，当满足告警条件时触发告警
2. 告警处理：发告警邮件 + dump所有进程
```
# example/alert_sys.yml

# 配置邮件账号
- config_email:
  host: smtp.qq.com
  password: $emailpass
  from_name: MonitorBoot
  from_email: ???@qq.com
  to_name: ???
  to_email: ???@qq.com

# 定时做系统告警
- schedule(10):
    - when_alert: # 发生告警时要执行以下步骤
        - send_alert_email: # 发告警邮件
        - dump_all_proc_xlsx: # dump所有进程
    - alert: # 告警
      # 告警条件
        - sys.mem_free <= 1024M # 剩余内存 <= 1024M
        - cpu_percent >= 90 # cpu使用率 >= 90%
      # - disk_percent >= 90 # 磁盘使用率 >= 90%
```

[运行视频](https://www.zhihu.com/zvideo/1637880842050281473)

### 5 监控jvm gc log并报警
[报警脚本](example/alert_jvm_gc.yml)
1. 订阅gc log文件变更，解析与检查gc指标，当满足告警条件时触发告警
2. 告警处理：发邮件+dump堆快照+dump线程栈+dump gc记录
```
# example/alert_jvm_gc.yml

# 准备：要先启动 kt-test 项目中的java主类 vm.chapter2.GcTestForMonitorBoot

# 配置邮件账号
- config_email:
  host: smtp.qq.com
  password: $emailpass
  from_name: MonitorBoot
  from_email: ???@qq.com
  to_name: ???
  to_email: ???@qq.com

# 监控进程的pid
- monitor_pid:
  grep: java | GcTestForMonitorBoot

# 监控gc日志
- monitor_gc_log(/home/shi/code/testing/kt-test/gc.log):
    - when_alert: # 发生告警时要执行以下步骤
        - send_alert_email: # 发告警邮件
        - dump_jvm_heap: # dump jvm堆快照(如果你监控了jvm进程)
        - dump_jvm_thread: # dump jvm线程栈(如果你监控了jvm进程)
        - dump_jvm_gcs_xlsx: # dump gc记录
    - alert: # 告警
      - ygc.costtime > 5 # gc耗时 > 5s
      - fgc.costtime > 5
      - fgc.interval < 10 # gc间隔时间 < 10s
```

[运行视频](https://www.zhihu.com/zvideo/1637882765587828736)
