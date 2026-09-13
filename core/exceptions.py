"""Custom exceptions for Lumentree integration."""


class LumentreeException(Exception):
    """Base exception for Lumentree integration."""

    pass


class ApiException(LumentreeException):
    """Exception for API-related errors.

    ``code`` is the vendor's ``returnValue`` for errors raised from a response
    that answered with one.  It is ``None`` for every other failure -- transport
    errors, timeouts, unparsable bodies, and the auth path, which raises
    :class:`AuthException` instead.  A caller that has to react to one specific
    return value reads this rather than matching against the message text.
    """

    def __init__(self, message: str, code: int | None = None) -> None:
        super().__init__(message)
        self.code = code


class AuthException(ApiException):
    """Exception for authentication errors."""

    pass


class MqttException(LumentreeException):
    """Exception for MQTT-related errors."""

    pass


class ParseException(LumentreeException):
    """Exception for data parsing errors."""

    pass
