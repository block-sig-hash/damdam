from collections.abc import Callable
from datetime import datetime
from uuid import UUID

from sqlmodel import Session, select

from app.profile.models import DeviceToken
from app.profile.schemas import DeviceTokenUpsert


class DeviceTokenService:
    def __init__(self, clock: Callable[[], datetime]) -> None:
        self.clock = clock

    def upsert(
        self,
        session: Session,
        user_id: UUID,
        payload: DeviceTokenUpsert,
    ) -> DeviceToken:
        token = session.exec(
            select(DeviceToken).where(DeviceToken.fcm_token == payload.fcm_token)
        ).first()
        if token is None:
            token = DeviceToken(
                user_id=user_id,
                fcm_token=payload.fcm_token,
                platform=payload.platform,
                updated_at=self.clock(),
            )
        else:
            # FCM registrations identify app installations. If a shared phone
            # signs into a different account, move that installation rather
            # than leaving notifications attached to the prior pilgrim.
            token.user_id = user_id
            token.platform = payload.platform
            token.updated_at = self.clock()
        session.add(token)
        session.commit()
        session.refresh(token)
        return token
