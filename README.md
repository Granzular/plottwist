# plottwist

**MATLAB to Python. Code to plots.**

plottwist is a web-based MATLAB-to-Python transpilation and visualization tool designed for Digital Signal Processing (DSP) coursework and experimentation.

It translates MATLAB code into Python using Groq-powered LLM inference, executes the generated Python code, and visualizes the results using Matplotlib.

## Overview

The goal of plottwist is to make it easier to work with MATLAB-based DSP exercises without requiring a MATLAB installation.

The application follows a simple workflow:

1. Write or paste MATLAB code.
2. Run the code through plottwist.
3. The application translates the MATLAB code into Python.
4. The generated Python code is executed.
5. Generated plots and execution output are displayed.
6. View and export the generated Python code and plots.

Generated Python code is displayed as read-only output. Users interact with the original MATLAB source rather than editing the translated code.

## Features

Planned functionality:

- MATLAB-to-Python translation using Groq inference.
- Python execution using NumPy, Matplotlib and SciPy.
- Multiple figure generation and visualization.
- Read-only display of translated Python code.
- Individual chart exports in PNG, PDF and DOCX formats.
- Combined multi-chart PDF and DOCX exports.
- CSV export for supported numerical data.
- Optional user accounts for saving generated plots.

## Technology Stack

| Component | Technology |
|---|---|
| Backend | Django |
| Frontend | Django Templates, JavaScript |
| Styling | Tailwind CSS |
| LLM inference | Groq |
| Numerical computing | NumPy |
| Plotting | Matplotlib |
| Scientific computing | SciPy |
| Database | SQLite |
| Dependency management | uv |

## Getting Started

### Requirements

- Python 3.13
- uv

### Installation

Clone the repository:

```bash
git clone https://github.com/Granzular/plottwist.git
cd plottwist
```

Install dependencies:

```bash
uv sync
```

Create an environment file:

```bash
cp .env.example .env
```

Configure the required environment variables in `.env`.

### Database setup

```bash
uv run python manage.py migrate
```

### Start the development server

```bash
uv run python manage.py runserver
```

Open `http://127.0.0.1:8000/` in your browser.

## Configuration

The application uses environment variables for configuration. Never commit API credentials or other secrets to the repository.

Refer to `.env.example` for the expected configuration variables.

## Project Status

plottwist is under active development.

The initial focus is MATLAB-to-Python translation, execution and visualization for DSP coursework. The translation implementation is designed to be replaceable with a native transpiler in the future.

## License

License not yet selected.
