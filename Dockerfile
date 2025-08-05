FROM ubuntu:latest

RUN apt update && apt install -y \
    python3 \
    make \
    git \
    stow \
    neovim \
    bash \
    curl \
    unzip \
    nodejs \
    npm \
    sqlite3

RUN npm install -g @anthropic-ai/claude-code @google/gemini-cli opencode-ai@latest

#RUN useradd -u 1000 -m -s /bin/bash player

RUN rm ~/.bashrc ~/.profile
RUN git clone https://github.com/spaderthomas/dotfiles.git ~/.dotfiles && \
    cd ~/.dotfiles && \
    chmod +x stow.sh && \
    ./stow.sh

ENV SHELL=/bin/bash

RUN curl -LsSf https://astral.sh/uv/install.sh | /bin/bash

CMD ["/bin/bash"]
