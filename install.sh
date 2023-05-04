#!/bin/sh
echo '卸载'
pip3.10 uninstall MonitorBoot -y

echo '清理旧包'
rm -rf dist/*

echo '打新包'
python3.10 setup.py sdist bdist_wheel

echo '安装到本地'
pip3.10 install dist/*.whl