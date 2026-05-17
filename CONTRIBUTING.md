# Contributing to LumentreeHA

Cảm ơn bạn đã quan tâm đóng góp! Dự án này được duy trì bởi một developer Việt Nam.

## How to contribute

### Report bugs
- Use the [bug report template](https://github.com/ngoviet/lumentreeHA/issues/new?template=bug_report.yml)
- Enable debug logging and include relevant logs
- Describe your Home Assistant version, integration version, and inverter model

### Suggest features
- Use the [feature request template](https://github.com/ngoviet/lumentreeHA/issues/new?template=feature_request.yml)
- Describe the problem and proposed solution

### Submit code
1. Fork the repo
2. Create a feature branch (`git checkout -b feature/my-feature`)
3. Make your changes
4. Test on your Home Assistant instance
5. Submit a pull request

### Code style
- Python 3.9+, Home Assistant 2023.1+
- Follow existing patterns in the codebase
- Use `__slots__` for new classes
- Log with module-level `_LOGGER`

## Development setup
1. Clone to `custom_components/lumentree/` in your HA config
2. Restart Home Assistant
3. Check logs for errors

## Support
If this project helps you, consider [buying me a coffee](https://buymeacoffee.com/ngoviet).
