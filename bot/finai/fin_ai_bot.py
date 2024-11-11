import base64
import io
import time

import requests
from requests import session

from bot.session_manager import SessionManager, Session
from bridge.reply import Reply, ReplyType
from common.log import logger
from config import conf
from bot.bot import Bot
from bridge.context import Context, ContextType
from PIL import Image


class FinAIBot(Bot):
    AUTH_FAILED_CODE = 401
    NO_QUOTA_CODE = 406

    def __init__(self):
        super().__init__()
        self.sessions = SessionManager(FinAISession, model=conf().get("model") or "gpt-3.5-turbo")
        self.args = {}

    def reply(self, query, context: Context = None) -> Reply:
        if context.type == ContextType.TEXT:
            return self._chat(query, context)
        elif context.type == ContextType.IMAGE:
            context.content = self._read_image(context.content)
            context.type = ContextType.TEXT
            return self._chat(context.content, context)
        else:
            reply = Reply(ReplyType.ERROR, "Bot不支持处理{}类型的消息".format(context.type))
        return reply

    def _chat(self, query, context, retry_count=0) -> Reply:
        """
        发起对话请求
        sessionId: 会话ID
        senderName: 发送者
        group: 是否群聊
        groupName: 群聊名
        queryText: 查询文本
        textType: 文本类型
        """
        if retry_count > 2:
            # exit from retry 2 times
            logger.warn("[FINAI] failed after maximum number of retry times")
            return Reply(ReplyType.TEXT, "请再问我一次吧")

        try:
            session_id = context["session_id"]
            query_text = query
            if context.type == ContextType.IMAGE:
                # 消息类型是图片，内容保存base64
                query_text = self._read_image(context.content)
            body = {
                "sessionId": session_id,
                "senderName": "",
                "group": False,
                "groupName": "",
                "queryText": query_text,
                "textType": str(context.type),
                "channelType": conf().get("channel_type", "wx")
            }
            if context.kwargs.get("msg"):
                body["sessionId"] = context.kwargs.get("msg").from_user_id
                if context.kwargs.get("msg").is_group:
                    body["group"] = True
                    body["groupName"] = context.kwargs.get("msg").from_user_nickname
                    body["senderName"] = context.kwargs.get("msg").actual_user_nickname
                else:
                    if body.get("channelType") in ["wechatcom_app"]:
                        body["senderName"] = context.kwargs.get("msg").from_user_id
                    else:
                        body["senderName"] = context.kwargs.get("msg").from_user_nickname

            headers = { }

            # do http request
            base_url = conf().get("finai_base_url", "http://localhost:2024")
            res = requests.post(url=base_url + "/finai/v1/chat/query", json=body, headers=headers,
                                timeout=conf().get("request_timeout", 180))
            if res.status_code == 200:
                # execute success
                response = res.json()
                """
                "requestId": 请求ID,
                "httpCode": http状态码,
                "cost": 消耗时间ms,
                "data": {
                    "sessionId": 会话ID,
                    "content": 响应内容,
                    "contentType": 内容类型,
                },
                "errorCode": 错误码,
                "errorMessage": 错误消息
                """
                data = response.get("data")
                if not data:
                    error_reply = "这个问题我还没有学会，请问我其它问题吧"
                    return Reply(ReplyType.TEXT, error_reply)
                content = data.get("content")
                content_type = data.get("contentType")
                session_id = data.get("sessionId")
                if content_type == str(ContextType.TEXT):
                    self.sessions.session_query(query = query, session_id = session_id)
                    self.sessions.session_reply(reply = content, session_id = session_id)
                elif content_type == str(ContextType.IMAGE):
                    # download image
                    return Reply(ReplyType.ERROR, "不支持处理{}类型的消息".format(content_type))
                else:
                    return Reply(ReplyType.ERROR, "不支持处理{}类型的消息".format(content_type))
                return Reply(ReplyType.TEXT, content)
            else:
                response = res.json()
                error = response.get("error")
                logger.error(f"[FINAI] chat failed, status_code={res.status_code}, "
                             f"msg={error.get('message')}, type={error.get('type')}")

                if res.status_code >= 500:
                    # server error, need retry
                    time.sleep(2)
                    logger.warn(f"[FINAI] do retry, times={retry_count}")
                    return self._chat(query, context, retry_count + 1)

                error_reply = "提问太快啦，请休息一下再问我吧"
                if res.status_code == 409:
                    error_reply = "这个问题我还没有学会，请问我其它问题吧"
                return Reply(ReplyType.TEXT, error_reply)
        except Exception as e:
            logger.exception(e)
            # retry
            time.sleep(2)
            logger.warn(f"[FINAI] do retry, times={retry_count}")
            return self._chat(query, context, retry_count + 1)

    def _read_image(self, path):
        """
        返回图片的内容，Base64编码
        """
        with Image.open(path) as img:
            # 图片转换成字节流
            bytes_io = io.BytesIO()
            img.save(bytes_io, format="PNG")
            bytes_io = bytes_io.getvalue()
        return base64.b64encode(bytes_io).decode("utf-8")

class FinAISession(Session):
    def __init__(self, session_id, system_prompt=None, model="qwen-turbo"):
        super().__init__(session_id)
        self.reset()