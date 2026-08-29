"""Self-contained Bluetooth Mesh + Godox vendor protocol implementation.

No Home Assistant imports live in this subpackage on purpose -- everything
here is plain Python + bleak + pycryptodome, so it can be tested, reused,
or ported independently of Home Assistant.
"""
