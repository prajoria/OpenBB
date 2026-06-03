# OpenBB FMP Cached Provider

FMP Cached extension for OpenBB with MySQL caching support.

## Overview

This provider extends the standard FMP (Financial Modeling Prep) provider with MySQL-based caching capabilities to improve performance and reduce API calls.

## Features

- MySQL database caching for FMP data
- Async database operations with aiomysql
- SQLAlchemy ORM support
- Compatible with OpenBB Platform v4.6.0+

## Requirements

- Python 3.10+
- MySQL database server
- OpenBB Core and FMP provider
- aiomysql, sqlalchemy dependencies

## Installation

This provider is installed as part of the OpenBB development environment setup.

## Configuration

Configure your MySQL connection and FMP API keys in the OpenBB user settings.