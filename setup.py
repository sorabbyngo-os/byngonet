from setuptools import setup, find_packages

setup(
    name="byngonet",
    version="0.2.0",
    description="Byngonet — AI-native distributed mesh network for Sorabbyngo OS",
    author="Sorabbyngo Labs",
    author_email="eng@sorabbyngo.com",
    url="https://github.com/sorabbyngo-Labs/byngonet",
    packages=find_packages(),
    python_requires=">=3.11",
    install_requires=[
        "nats-py>=2.6.0",
        "cryptography>=42.0.0",
        "orjson>=3.9.0",
    ],
    extras_require={
        "dev": ["pytest", "pytest-asyncio"],
    },
    entry_points={
        "console_scripts": [
            "byngonet-node=main:main",
        ],
    },
)
