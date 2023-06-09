import smtplib
import socket
from email.header import Header
from email.mime.text import MIMEText

# 配置
config = {
    'host': '',
    'password': '',
    'from_name': '',
    'from_email': '',
    # 'to_email': '',
    # 'to_name': '',
}

# 配置邮件
def config_email(config2):
    global config
    config = config2

# 发邮件
def send_email(title, msg, to_email = None, to_name = None):
    # 收件人默认从配置中取
    if to_email is None and to_name is None:
        to_email = config['to_email']
        to_name = config['to_name']
    if to_name is None:
        to_name = to_email

    message = MIMEText(msg, 'plain', 'utf-8')  # Chinese required 'utf-8'
    message['Subject'] = Header(title, 'utf-8')
    message['From'] = f"{config['from_name']} <{config['from_email']}>"
    message['To'] = to_email

    do_send_email(message, to_email)

# 真正的发邮件
def do_send_email(message, to_email):
    smtp = login()
    smtp.sendmail(config['from_email'], to_email, message.as_string())
    smtp.quit()

# 登录邮件server
_smtp = None
def login():
    global _smtp
    if _smtp is None:
        try:
            _smtp = smtplib.SMTP_SSL(config['host'], 465)  # qq邮箱
        except socket.error:
            _smtp = smtplib.SMTP(config['host'], 25)  # 163邮箱
        _smtp.login(config['from_email'], config['password'])
    return _smtp


if __name__ == '__main__':
    send_email(1)
