# Imagem do portao de fumaca.
#
# A imagem oficial traz os navegadores em /ms-playwright, mas nao o pacote
# `playwright` — ela espera que o projeto instale o seu. Instalamos uma vez
# aqui para o portao nao depender de rede a cada publicacao.
FROM mcr.microsoft.com/playwright:v1.49.0-jammy
RUN npm install -g playwright@1.49.0
ENV NODE_PATH=/usr/lib/node_modules
