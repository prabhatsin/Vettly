
#! makes a token that lets one specific person join one specific interview room on your LiveKit server.

from datetime import timedelta

from livekit import api

from app.config import settings


def room_name_for(application_id) -> str:
    return f"interview-{application_id}"


def create_room_token(identity: str, name: str, room: str) -> str:
    token = (
        api.AccessToken(settings.livekit_api_key, settings.livekit_api_secret)
        .with_identity(identity)
        .with_name(name)
        .with_grants(api.VideoGrants(room_join=True, room=room))
        .with_ttl(timedelta(hours=1))
    )
    return token.to_jwt()