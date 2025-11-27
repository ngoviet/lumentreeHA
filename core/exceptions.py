"""Custom exceptions for Lumentree integration."""


class LumentreeException(Exception):
    """Base exception for Lumentree integration."""

    pass


class ApiException(LumentreeException):
    """Exception for API-related errors."""

    pass


class AuthException(ApiException):
    """Exception for authentication errors."""

    pass


class MqttException(LumentreeException):
    """Exception for MQTT-related errors."""

    pass


class ParseException(LumentreeException):
    """Exception for data parsing errors."""

    pass

