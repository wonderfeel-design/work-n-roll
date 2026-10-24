def pytest_configure(config):
    config.addinivalue_line("markers", "gemma: calls the Gemini API (slow, uses quota)")
    config.addinivalue_line("markers", "elevenlabs: calls ElevenLabs (uses credits)")
