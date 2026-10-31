# FUT7 Manager

MVP em Python/Streamlit para gestão de elenco de Futebol 7, escalações, metas, estatísticas, avaliações anônimas e cards de atleta com radar hexagonal.

## Aplicação web conectada

A pasta `frontend` usa uma API Starlette no arquivo `web_app.py`, compartilhando autenticação, modelos e banco SQLAlchemy com o MVP Streamlit. Treinadores podem criar time e PIN; atletas criam conta após validar o convite. O painel permite cadastrar partidas e convocar qualquer quantidade de jogadores, sem exigir posição ou formação fixa. Titulares podem ser posicionados livremente no mapa do campo. A API valida permissões e mantém cada operação isolada pelo time.

## Requisitos

- Python 3.10 ou superior
- Git (opcional para controle de versão)

## Executar localmente

No PowerShell, na pasta do projeto:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

Para abrir a interface web conectada, inicie o servidor Starlette:

```powershell
python -m uvicorn web_app:app --host 127.0.0.1 --port 8503
```

Acesse `http://127.0.0.1:8503`. No primeiro acesso, selecione **Criar conta → Sou treinador**, cadastre o time e defina um PIN numérico de 6 a 12 dígitos. O jogador cria sua conta com e-mail e senha, informa os dados físicos e valida o PIN do time. Depois do login, o treinador pode cadastrar uma partida no painel com adversário, data, horário, local e escalação. Após o jogo, registre o placar, gols e assistências por atleta, além dos cartões amarelos e vermelhos. O placar do time deve corresponder à soma dos gols individuais. O banco local padrão é `data\fut7.db`; os dados da aplicação Streamlit continuam disponíveis nesse mesmo banco.

Para iniciar a interface Streamlit, use em outro terminal:

```powershell
python -m streamlit run app.py
```

Para apontar para outro banco, defina `FUT7_DATABASE_URL`, por exemplo:

```powershell
$env:FUT7_DATABASE_URL = "sqlite:///C:/dados/fut7.db"
```

`schema.sql` documenta o esquema relacional; as tabelas em execução são criadas pelas entidades SQLAlchemy em `fut7\models.py`.

## Escopo do MVP

- **Treinador:** conta vinculada a um time, envio do escudo e definição do PIN de convite, criação de partidas, convocação, edição/desativação de atletas, registro de estatísticas, metas e relatórios.
- **Atleta:** cria a conta e preenche o perfil antes de selecionar o time e validar o PIN; consulta o card, a escalação e as metas, registra progresso e avalia companheiros convocados.
- **Isolamento:** jogadores, partidas, metas e relatórios são limitados ao time associado à sessão.
- **PIN de convite:** o treinador define ou troca o PIN em **Time & convite**. Ele é armazenado como hash e não pode ser recuperado; para compartilhar um código novo, o treinador deve atualizá-lo.
- **Escudo e posições:** o escudo do time e a posição secundária do atleta são persistidos no banco; imagens de escudo aceitam PNG, JPEG ou WebP de até 2 MB.
- **Foto do card:** aceita URL HTTP/HTTPS informada pelo atleta ou treinador; sem foto, exibe avatar com iniciais.
- **Avaliação:** uma nota anônima de 0 a 5 por atleta avaliado e partida. O sistema não exibe a identidade do avaliador; a nota final somente aparece quando existem nota técnica e pelo menos uma avaliação: `(média dos companheiros + nota técnica) / 2`.
- **Card:** nota geral de 0 a 99 derivada da média dos seis atributos; foto e molduras de raridade são pontos de extensão visual.

## Dados e fórmula do radar

As seis dimensões (ATA, DEF, FOR, VEL, TEC e INT) são estimativas em escala 0–100, calculadas em `fut7\logic.py`. A função usa médias por partida de gols, assistências, chutes no alvo, desarmes, disciplina, avaliações e notas do treinador. Força e velocidade incluem um componente de perfil baseado em altura/IMC. Dados ausentes usam um perfil neutro; a interface informa que não são medições físicas. Ajuste pesos e limites após validar com o treinador e dados reais.

Tabelas centrais: `teams`, `users`, `web_sessions`, `matches`, `match_roster`, `player_stats`, `goals` e `ratings`. Usuários e partidas pertencem a um time; `match_roster` determina quem pode avaliar em uma partida. Avaliações usam restrições de unicidade no banco para evitar duplicidade. Resultados e estatísticas individuais são gravados em `matches` e `player_stats`.

## Estrutura

```text
app.py                 Navegação e telas Streamlit
web_app.py             API Starlette e frontend web conectado
fut7/
  database.py          Engine, sessões e inicialização SQLite/PostgreSQL
  models.py            Entidades SQLAlchemy e relacionamentos
  logic.py             Overall, atributos e nota final
  registration.py      Validação de e-mail e processamento seguro do escudo
  security.py          Hash e verificação de senha
  ui.py                Tema, card Ultimate Team e radar Plotly
schema.sql             Esquema SQL de referência
.streamlit/
  config.toml          Limite de upload para os escudos
requirements.txt
```

## Roadmap de implementação

1. Criar ambiente virtual e instalar `requirements.txt`; iniciar a aplicação com Streamlit.
2. Criar a conta do treinador/time e definir o PIN; compartilhar nome do time e PIN com os atletas convidados.
3. Após os atletas criarem o acesso, preencherem o perfil e validarem o PIN do time, criar a partida, convocá-los e posicionar titulares opcionalmente no mapa tático.
4. Após o jogo, lançar estatísticas e nota técnica; atualizar metas dos atletas.
5. Os atletas entram com as contas criadas após validar o convite e avaliam os companheiros convocados.
6. Usar cards e relatórios para discutir desempenho; calibrar os pesos dos atributos junto ao treinador.
7. Antes de produção: migrar de `create_all` para Alembic, usar PostgreSQL gerenciado, configurar HTTPS/segredos, autorização de cadastro, política de retenção e auditoria, backups e testes automatizados.

Ao abrir um banco local criado pela versão anterior, a inicialização cria o time legado do treinador existente e associa os dados históricos a ele. O PIN legado não é recuperável; o treinador deve definir um novo em **Time & convite**.

## Testes

```powershell
python -m unittest discover -s tests -v
```

A suíte valida regras de cadastro, processamento de escudos, autenticação, cálculo dos atributos e o fluxo web de treinador, atleta, escalação e resultado. O teste web usa um banco temporário e não altera `data\fut7.db`.

## Uso de GitHub Copilot

Abra a pasta no VS Code, selecione um interpretador dentro de `.venv` e use o Copilot Chat para pedir mudanças pequenas e verificáveis (por exemplo, “adicione filtros por temporada ao relatório”). Revise diffs, regras de acesso e fórmulas antes de aceitar alterações; rode a aplicação e valide os fluxos de treinador e atleta.

## Limites e próximos passos

Este MVP é uma base funcional para prototipagem, não um sistema de produção. O servidor web usa sessão persistida em cookie HttpOnly/SameSite e vincula cada escalação ao time do treinador autenticado; configure `FUT7_COOKIE_SECURE=1` quando servido sobre HTTPS. O PIN é compartilhado por time e deve ser trocado se vazar. Antes de expor a aplicação à internet, adicione limitação de tentativas, convites individuais com expiração, HTTPS, proteção CSRF mais abrangente, política de retenção, logs, backups e testes de segurança. A identidade anônima das avaliações é ocultada na interface, mas não é anonimato criptográfico: um administrador com acesso direto ao banco consegue relacionar avaliador e nota. A escalação aceita qualquer quantidade de titulares e reservas, e as posições no campo são opcionais; o registro de resultados e as avaliações continuam vinculados aos jogadores convocados.
