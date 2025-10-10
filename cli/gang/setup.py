from setuptools import setup, find_packages

setup(
    name='gang-cli',
    version='1.0.0',
    packages=find_packages(),
    install_requires=[
        'click>=8.0.0',
        'pyyaml>=6.0',
        'anthropic>=0.18.0',
        'beautifulsoup4>=4.12.0',
    ],
    entry_points={
        'console_scripts': [
            'gang=cli:cli',
        ],
    },
)
