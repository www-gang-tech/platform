from setuptools import setup

setup(
    name='gang-cli',
    version='1.0.0',
    py_modules=['cli'],
    install_requires=[
        'click>=8.0.0',
        'pyyaml>=6.0',
        'markdown>=3.4.0',
        'anthropic>=0.18.0',
        'beautifulsoup4>=4.12.0',
    ],
    entry_points={
        'console_scripts': [
            'gang=cli:cli',
        ],
    },
)
