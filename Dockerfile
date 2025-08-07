FROM ubuntu:latest

RUN apt update && apt install -y \
    bash \
    curl \
    fzf \
    git \
    make \
    neovim \
    nodejs \
    npm \
    python3 \
    sqlite3 \
    stow \
    unzip

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
