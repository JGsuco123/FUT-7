# CLUB//MODE — Aplicação web de Futebol 7

Esta interface web responsiva usa a API Starlette em `web_app.py` e o mesmo banco SQLAlchemy/SQLite do MVP Streamlit. Não abra `index.html` diretamente: autenticação e gravação exigem que o servidor esteja ativo.

## Executar

Na raiz do projeto, com o ambiente virtual ativado e dependências instaladas:

```powershell
python -m uvicorn web_app:app --host 127.0.0.1 --port 8503
```

Abra `http://127.0.0.1:8503`. O banco padrão é `data\fut7.db`. Para trocar de banco, configure `FUT7_DATABASE_URL` antes de iniciar o servidor.

## Fluxos conectados

- **Treinador:** cadastro persistente com nome, e-mail, senha, time, escudo e PIN de convite; login/logout por cookie HttpOnly; cadastro de partidas com data e horário, escalações e registro posterior do placar, gols, assistências e cartões.
- **Jogador:** cadastro por etapas, incluindo dados físicos, posição e PIN do time; login e visualização do elenco/partida do seu time.
- **Escalação:** qualquer quantidade de titulares e reservas, sem exigir posição ou formação fixa. O treinador pode posicionar os titulares livremente no mapa do campo; as coordenadas são persistidas e continuam editáveis. O servidor valida se os atletas pertencem ao time e estão ativos.
- **Cards e radar:** atributos calculados a partir de estatísticas, notas do treinador e avaliações usando a lógica compartilhada `fut7/logic.py`.
- **Times públicos:** o catálogo revela somente escudo e nome, sem e-mails ou PINs.

## Estrutura

- `index.html`: cadastro, navegação, painel tático e telas.
- `styles.css`: identidade visual, componentes e breakpoints móveis.
- `app.js`: integração HTTP, renderização dos dados persistidos e interações da escalação.
- `../web_app.py`: API de autenticação, equipes, partidas, escalações e resultados.

## Validação

Na raiz do projeto, execute `python -m unittest discover -s tests -v`. Os testes de API usam banco temporário e cobrem conta de treinador, convite do jogador, autenticação, isolamento e persistência de escalação.
