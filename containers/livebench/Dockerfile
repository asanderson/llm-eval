# Build context: the pinned LiveBench checkout created by scripts/setup.py.
# Resulting image ID is recorded by each run; no runtime network is granted to graders.
ARG PYTHON_BASE=python:3.12-slim-bookworm
FROM ${PYTHON_BASE}
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 PYTHONDONTWRITEBYTECODE=1 PYTHON_DOTENV_DISABLED=1
RUN apt-get update && apt-get install -y --no-install-recommends build-essential git \
    && rm -rf /var/lib/apt/lists/*
COPY . /opt/livebench
RUN python -m pip install /opt/livebench \
    && python -m spacy download en_core_web_sm \
    && python -c "import nltk; [nltk.download(x, download_dir='/usr/local/share/nltk_data') for x in ['punkt','punkt_tab','wordnet','omw-1.4','averaged_perceptron_tagger','averaged_perceptron_tagger_eng']]" \
    && python -m pip freeze --all > /opt/dependencies.txt
WORKDIR /work
