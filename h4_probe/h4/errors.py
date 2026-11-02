class MQTTError(Exception):
    """Safe, user-facing MQTT error without credentials or raw responses."""
