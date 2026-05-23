"""Setup configuration for crypto-portfolio-manager."""

from setuptools import setup, find_packages
from pathlib import Path

# Read README for long description
readme_file = Path(__file__).parent / 'README.md'
long_description = readme_file.read_text() if readme_file.exists() else ''

setup(
    name='crypto-portfolio-manager',
    version='1.0.0',
    author='Vladi',
    description='Cryptocurrency portfolio monitoring, analysis, and recommendation system',
    long_description=long_description,
    long_description_content_type='text/markdown',
    url='https://github.com/yourusername/crypto-portfolio-manager',
    package_dir={'': 'src'},
    packages=find_packages(where='src'),
    python_requires='>=3.8',
    install_requires=[
        'requests>=2.31.0',
        'numpy>=1.24.0',
        'python-dateutil>=2.8.2',
    ],
    extras_require={
        'telegram': ['python-telegram-bot>=20.0'],
        'dev': ['pytest>=7.4.0', 'black', 'flake8'],
    },
    entry_points={
        'console_scripts': [
            'crypto-portfolio=crypto_portfolio.cli:main',
        ],
    },
    classifiers=[
        'Development Status :: 4 - Beta',
        'Intended Audience :: Developers',
        'Intended Audience :: Financial and Insurance Industry',
        'License :: OSI Approved :: MIT License',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.8',
        'Programming Language :: Python :: 3.9',
        'Programming Language :: Python :: 3.10',
        'Programming Language :: Python :: 3.11',
    ],
)
