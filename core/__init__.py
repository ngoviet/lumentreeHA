"""Core business logic for Lumentree integration.

This package contains the core functionality, one submodule per concern:

- :mod:`~core.api_client` -- ``LumentreeHttpApiClient``, HTTP communication
- :mod:`~core.mqtt_client` -- ``LumentreeMqttClient``, real-time MQTT client
- :mod:`~core.realtime_parser` -- Modbus-RTU payload decoding
- :mod:`~core.exceptions` -- the exception hierarchy

Nothing is re-exported here on purpose.  ``mqtt_client`` and ``api_client``
import Home Assistant, so a re-export would pull Home Assistant in for any
caller that only wanted, say, the exception classes.  Import the submodule
directly instead.
"""
