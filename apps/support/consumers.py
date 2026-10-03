"""Live dashboard channel: new-order alerts and new support chat messages for staff."""

from channels.generic.websocket import AsyncJsonWebsocketConsumer


class DashboardConsumer(AsyncJsonWebsocketConsumer):
    group = "dashboard"

    async def connect(self):
        user = self.scope.get("user")
        if not user or not user.is_authenticated or not getattr(user, "is_dashboard_user", False):
            await self.close(code=4403)
            return
        await self.channel_layer.group_add(self.group, self.channel_name)
        await self.accept()

    async def disconnect(self, code):
        await self.channel_layer.group_discard(self.group, self.channel_name)

    async def new_order(self, event):
        await self.send_json({"type": "new_order", "order_id": event["order_id"]})

    async def chat_message(self, event):
        await self.send_json({"type": "chat_message", "chat": event["chat"], "text": event["text"][:200]})
