"""Dormant SMTP submission adapter. Never imported by preview workflow.

Connection and submission are forbidden unless the caller explicitly grants a
test/production send, AND the dedicated environment approval is present.
No emails or credentials are logged or persisted.
"""
from __future__ import annotations
import os
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import parseaddr
from ccf_r63_delivery import SafetyError

def valid_mailbox(text):
    raw=str(text or "").strip()
    name,addr=parseaddr(raw)
    if name or raw!=addr or addr.count("@")!=1 or " " in addr or "\n" in addr or "\r" in addr:
        raise SafetyError("Invalid email identity")
    return addr

class SmtpSender:
    def __init__(self,*,test_mode=True,env=None):
        self.env=os.environ if env is None else env
        expected="TEST_ONLY" if test_mode else "DAILY_APPROVED"
        if self.env.get("CCF_SMTP_AUTHORIZATION")!=expected:
            raise SafetyError("Separate, explicit SMTP authorization is required")
        self.sender=valid_mailbox(self.env.get("SENDER"))
        self.receiver=valid_mailbox(self.env.get("RECEIVER"))
        self.password=str(self.env.get("SENDER_PASSWORD") or "")
        if not self.password:raise SafetyError("Sender credential missing")
        self.test_mode=test_mode
    def submit(self,html_bytes,*,task_id):
        if not isinstance(html_bytes,bytes) or not html_bytes:
            raise SafetyError("Finalized HTML bytes required")
        message=EmailMessage()
        message["From"]=self.sender
        message["To"]=self.receiver
        message["Subject"]=("[TEST] " if self.test_mode else "")+"CCF A 类论文每日推荐"
        message["X-CCF-Batch-ID"]=task_id
        message.set_content("请在支持 HTML 的邮件客户端查看本次 CCF 论文推荐。")
        message.add_alternative(html_bytes.decode("utf-8"),subtype="html")
        # Never auto-retry an unknown SMTP result. Only successful server
        # submission is reported, not confirmation of inbox delivery.
        with smtplib.SMTP_SSL("smtp.qq.com",465,timeout=35,
                              context=ssl.create_default_context()) as client:
            client.login(self.sender,self.password)
            refused=client.send_message(message)
            if refused:
                raise RuntimeError("One or more recipients were rejected")
        return True
