# Інструкція для агента: розгортання сервера

Цей документ — для Claude Code (або іншого агента), який працює на комп'ютері власниці проєкту й має SSH-доступ до сервера. На сервері треба розгорнути **два окремі сервіси**:

1. **claude-gateway** — шлюз Claude Code (HTTP API + MCP) з окремого репозиторію [FixerHack/claude-gateway](https://github.com/FixerHack/claude-gateway). Це самостійний сервіс, яким може користуватися будь-яка програма на сервері, не лише Tension Index. Він живе у власній теці `~/claude-gateway` і має свій `.env`, свій systemd-юніт і своє оновлення.
2. **war-predictor (Tension Index)** — бот і таймери збору даних, у теці `~/war-predictor`. До шлюзу він звертається як звичайний клієнт: через `GATEWAY_URL` і токен.

Ці два сервіси не мають спільних файлів, віртуальних середовищ, `.env` чи юнітів. Оновлення, перезапуск чи видалення одного не зачіпає іншого. Кожен має власний репозиторій.

Пиши власниці українською й не звертайся до неї на ім'я.

## Правила

1. **Секрети не друкуй.** Токени (`TELEGRAM_BOT_TOKEN`, `CLAUDE_CODE_OAUTH_TOKEN`, `GATEWAY_TOKENS`, `GATEWAY_TOKEN`) не виводь у чат, не логуй і не передавай аргументами команд, які потрапляють в історію shell. Перевіряй лише, що рядок не порожній: `grep -c '^KEY=.\+' файл`.
2. **Перед руйнівними чи незворотними діями питай.** Сюди входять видалення файлів чи баз, перевстановлення системи, зміни фаєрволу, відкриття портів назовні, перезапуск чужих сервісів і `apt upgrade` усієї системи. Встановлення наших залежностей і запуск наших інсталяторів дозволені.
3. **Порти назовні не відкривай.** Шлюз слухає лише `127.0.0.1:8787`. HTTPS-проксі для доступу ззовні — окремий крок, лише за явною згодою власниці.
4. **Не змішуй сервіси.** Шлюз ставиться тільки з `~/claude-gateway` через його `scripts/install.sh`, а бот тільки з `~/war-predictor` через `scripts/install_server.sh`.
5. **Не запускай два боти з одним токеном Telegram.** Перед стартом бота на сервері зупини локальний (крок 2).
6. **Не змінюй код у репозиторії.** Якщо скрипт падає через помилку в коді, опиши її (команда, вивід, гіпотеза) і зупинись, без латок на сервері.
7. **Звітуй коротко після кожного етапу:** що зроблено, що перевірено, що далі.

## Що потрібно від власниці

Спитай, якщо цього немає:
- **SSH-доступ:** `користувач@адреса` (і порт, якщо не 22). Користувач має мати `sudo`.
- **Згода** перенести на сервер значення Telegram з локального `.env` проєкту.
- **Токен Claude Code** з `claude setup-token` на її комп'ютері. Вписує його вона сама (крок 4).

## Кроки

### 1. Перевірка доступу й сервера

```bash
ssh USER@HOST 'cat /etc/os-release | head -3; id; sudo -n true && echo SUDO_OK || echo SUDO_NEEDS_PASSWORD; systemctl --version | head -1; df -h ~ | tail -1; free -h | head -2; ss -ltn | grep -E ":8787 " || echo PORT_8787_FREE'
```

Що має бути:
- ОС Debian або Ubuntu;
- є systemd;
- щонайменше 2 ГБ вільного диска і 1 ГБ RAM;
- порт 8787 вільний.

Якщо `sudo` питає пароль, команди з `sudo` власниця вводитиме сама (`ssh -t`). Пароль у чат не проси.

```bash
ssh USER@HOST 'command -v git >/dev/null || sudo apt-get install -y git curl python3'
```

### 2. Зупинити локальний бот

Локально, у теці проєкту на Mac:

```bash
pkill -f "tension-index bot" || true
```

Якщо бот працює в іншому терміналі, попроси власницю натиснути там Ctrl+C.

---

## Частина A. claude-gateway (окремий сервіс)

### 3. Код шлюзу у власній теці

```bash
ssh USER@HOST 'test -d ~/claude-gateway && (cd ~/claude-gateway && git pull --ff-only) || git clone https://github.com/FixerHack/claude-gateway.git ~/claude-gateway'
ssh USER@HOST 'ls ~/claude-gateway'
```

У теці мають бути `pyproject.toml`, `uv.lock`, `scripts/` і `src/`. Якщо `git clone` питає логін, репозиторій приватний: зупинись і попроси власницю зробити його публічним або додати deploy key.

### 4. Встановлення й вхід Claude Code

```bash
ssh -t USER@HOST 'cd ~/claude-gateway && ./scripts/install.sh'
```

Скрипт ставить uv і Claude Code, створює `.env` зі згенерованим `GATEWAY_TOKENS` і встановлює юніт `claude-gateway.service`. Якщо Claude Code ще не залогінений, скрипт зупиниться з підказкою. Тоді:

1. Попроси власницю виконати на її Mac `claude setup-token`. Команда відкриє браузер і надрукує токен.
2. Попроси її **самій** вписати токен на сервері, щоб він не проходив через чат:
   ```bash
   ssh -t USER@HOST 'nano ~/claude-gateway/.env'   # рядок CLAUDE_CODE_OAUTH_TOKEN=...
   ```
3. Перевір і запусти скрипт ще раз:
   ```bash
   ssh USER@HOST 'grep -c "^CLAUDE_CODE_OAUTH_TOKEN=.\+" ~/claude-gateway/.env'   # має бути 1
   ssh -t USER@HOST 'cd ~/claude-gateway && ./scripts/install.sh'
   ```

### 5. Перевірка шлюзу

```bash
ssh USER@HOST 'systemctl is-active claude-gateway; curl -fsS http://127.0.0.1:8787/health'
ssh USER@HOST 'cd ~/claude-gateway && set -a && . ./.env && set +a && curl -s -m 60 http://127.0.0.1:8787/v1/complete -H "Authorization: Bearer ${GATEWAY_TOKENS%%,*}" -H "Content-Type: application/json" -d "{\"prompt\":\"Reply with OK\"}" | head -c 300'
```

Що має бути: `active`, `{"ok":true,...}` і відповідь з `"text":"OK"`.

### 6. Окремий токен для war-predictor

Кожен клієнт шлюзу має отримати власний токен, щоб його доступ можна було відкликати окремо. Додай до `GATEWAY_TOKENS` другий токен, нічого не друкуючи:

```bash
ssh USER@HOST 'cd ~/claude-gateway && T=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))") && sed -i "s/^GATEWAY_TOKENS=\(.\+\)$/GATEWAY_TOKENS=\1,$T/" .env && printf "%s" "$T" > ~/.war-predictor-gateway-token && chmod 600 ~/.war-predictor-gateway-token && sudo systemctl restart claude-gateway'
```

Токен тимчасово лежить у `~/.war-predictor-gateway-token`. У кроці 9 він переїде в `.env` бота, а файл буде видалено.

---

## Частина B. war-predictor (бот і таймери)

### 7. Код бота

```bash
ssh USER@HOST 'test -d ~/war-predictor && (cd ~/war-predictor && git pull --ff-only) || git clone https://github.com/FixerHack/war-predictor.git ~/war-predictor'
ssh USER@HOST 'cd ~/war-predictor && ./scripts/install_server.sh'
```

Перший запуск створює `.env` і зупиняється. У ньому вже стоять `CLASSIFIER_PROVIDER=gateway` і `GATEWAY_URL=http://127.0.0.1:8787`.

### 8. Значення Telegram з локального `.env`

Лише з дозволу власниці. Команди виконуй у теці проєкту на Mac; значення не друкуються:

```bash
for key in TELEGRAM_BOT_TOKEN TELEGRAM_CHAT_ID TELEGRAM_ADMIN_IDS HEALTH_PING_URL; do
  line="$(grep -E "^${key}=" .env | tail -1)"
  [ -n "$line" ] && printf '%s\n' "$line" | ssh USER@HOST "cd ~/war-predictor && grep -v '^${key}=' .env > .env.tmp; cat >> .env.tmp; mv .env.tmp .env; chmod 600 .env"
done
ssh USER@HOST 'cd ~/war-predictor && for k in TELEGRAM_BOT_TOKEN TELEGRAM_CHAT_ID TELEGRAM_ADMIN_IDS; do printf "%s: " $k; grep -c "^$k=.\+" .env; done'
```

Кожен ключ має показати `1`. Не перенось `CLASSIFIER_PROVIDER`, `CLAUDE_CODE_BIN` і `DATABASE_PATH`, бо на сервері вони свої.

### 9. Токен шлюзу в `.env` бота

```bash
ssh USER@HOST 'cd ~/war-predictor && T=$(cat ~/.war-predictor-gateway-token) && grep -v "^GATEWAY_TOKEN=" .env > .env.tmp && printf "GATEWAY_TOKEN=%s\n" "$T" >> .env.tmp && mv .env.tmp .env && chmod 600 .env && rm -f ~/.war-predictor-gateway-token && grep -c "^GATEWAY_TOKEN=.\+" .env'
```

### 10. Встановлення бота

```bash
ssh -t USER@HOST 'cd ~/war-predictor && ./scripts/install_server.sh'
```

Скрипт встановлює юніти бота й таймерів. Наприкінці він перевіряє, що шлюз відповідає за `GATEWAY_URL`.

### 11. Перевірка всього разом

```bash
ssh USER@HOST 'systemctl is-active claude-gateway tension-bot; systemctl list-timers "tension-*" --no-pager | head -12'
ssh USER@HOST 'cd ~/war-predictor && ./scripts/run.sh run 2>&1 | tail -15'
ssh USER@HOST 'cd ~/war-predictor && ./scripts/healthcheck.sh; echo exit=$?'
ssh USER@HOST 'journalctl -u tension-bot -n 30 --no-pager'
```

Що має бути:
- обидва сервіси `active`;
- у `run` рядок `classified: ... 'claude': N` з N > 0, а в кінці `scores: 38/38 published`;
- healthcheck завершується з `exit=0` (OK) або `1` (WARN, допустимо в першу добу);
- у логах бота немає помилок, а `/start` у Telegram показує дашборд. Попроси власницю перевірити.

Перевір, що сервіси справді розділені: у `claude-gateway` немає посилань на `war-predictor`, а бот не залежить від файлів шлюзу.

```bash
ssh USER@HOST 'systemctl cat claude-gateway | grep -E "WorkingDirectory|EnvironmentFile"; systemctl cat tension-bot | grep -E "WorkingDirectory"'
```

Очікувано: `/home/USER/claude-gateway` у шлюзу і `/home/USER/war-predictor` у бота (для `root` — `/root/...`).

---

## Частина C. Публічна карта (GitHub Pages)

### 12. Ключ для публікації карти

Сервер кожні 30 хвилин публікує карту в гілку `gh-pages` (`tension-pages.timer`), лише коли дані змінилися. Для цього йому потрібен deploy key із правом запису. Ключ створюєш ти, а додає його на GitHub власниця. Приватний ключ нікуди не виводь; публічний можна показати.

```bash
ssh USER@HOST 'test -f ~/.ssh/war-predictor-pages || ssh-keygen -q -t ed25519 -N "" -C "war-predictor pages" -f ~/.ssh/war-predictor-pages; grep -q "^Host github-pages$" ~/.ssh/config 2>/dev/null || printf "Host github-pages\n  HostName github.com\n  User git\n  IdentityFile ~/.ssh/war-predictor-pages\n  IdentitiesOnly yes\n" >> ~/.ssh/config; chmod 600 ~/.ssh/config; ssh-keyscan -t ed25519 github.com 2>/dev/null >> ~/.ssh/known_hosts; cat ~/.ssh/war-predictor-pages.pub'
```

Попроси власницю: GitHub → репозиторій `war-predictor` → Settings → Deploy keys → Add deploy key, назва `server-pages`, вставити надрукований публічний ключ і **поставити галочку Allow write access**. Коли вона підтвердить:

```bash
ssh USER@HOST 'ssh -T git@github-pages 2>&1 | head -1'   # "Hi FixerHack/war-predictor! You've successfully authenticated..."
ssh USER@HOST 'cd ~/war-predictor && grep -v "^PAGES_REMOTE=" .env > .env.tmp && echo "PAGES_REMOTE=git@github-pages:FixerHack/war-predictor.git" >> .env.tmp && mv .env.tmp .env && chmod 600 .env && ./scripts/install_server.sh 2>&1 | tail -5'
ssh USER@HOST 'sudo systemctl start tension-pages.service; systemctl is-failed tension-pages.service; journalctl -u tension-pages -n 5 --no-pager'
```

Очікувано: `inactive` (не `failed`) і в журналі `Published` або `Nothing changed on gh-pages`. Через хвилину-дві карта на https://fixerhack.github.io/war-predictor/dashboard/ показує серверні дані.

### 13. Звіт

Наприкінці дай власниці короткий звіт:
- **що працює:** сервіси `claude-gateway` і `tension-bot`, таймери, де лежить кожен сервіс;
- **результати перевірок** з кроків 5 і 11;
- **оновлення (окремо для кожного):**
  - шлюз: `ssh USER@HOST 'cd ~/claude-gateway && git pull --ff-only && ./scripts/install.sh'`;
  - бот: `ssh USER@HOST 'cd ~/war-predictor && ./scripts/deploy.sh'`;
- **логи:** `journalctl -u claude-gateway -f`, `journalctl -u tension-bot -f`;
- **як дати шлюз іншій програмі:** додати ще один токен до `GATEWAY_TOKENS` (як у кроці 6), перезапустити `claude-gateway` і передати програмі URL та цей токен;
- **що лишилось за нею:** HTTPS для шлюзу ззовні (якщо потрібно), `HEALTH_PING_URL`, захист `main` на GitHub. Повний перелік: [docs/owner-steps.md](owner-steps.md).

## Перенесення шлюзу зі старої схеми

До жовтня 2026 шлюз жив у `war-predictor/gateway/` і на сервер потрапляв sparse-клоном у `~/claude-gateway/gateway`. Якщо `systemctl cat claude-gateway` показує `WorkingDirectory=.../claude-gateway/gateway`, перенеси його на окремий репозиторій. Так зберігаються `.env` і всі токени, а простій становить кілька секунд (бот тим часом класифікує правилами):

```bash
ssh USER@HOST 'set -e; mv ~/claude-gateway ~/claude-gateway.old && git clone -q https://github.com/FixerHack/claude-gateway.git ~/claude-gateway && cp -p ~/claude-gateway.old/gateway/.env ~/claude-gateway/.env && cd ~/claude-gateway && ./scripts/install.sh 2>&1 | tail -3'
ssh USER@HOST 'systemctl cat claude-gateway | grep WorkingDirectory; curl -fsS http://127.0.0.1:8787/health'
```

Потім повтори перевірку токена бота (крок 11). Стару теку `~/claude-gateway.old` видаляй лише з дозволу власниці.

## Типові проблеми

| Симптом | Що робити |
|---|---|
| `TELEGRAM_BOT_TOKEN is empty in .env` | крок 8 не завершено |
| `claude not found after install` | `ssh USER@HOST 'ls ~/.local/bin; echo $PATH'`, встановити вручну: `curl -fsSL https://claude.ai/install.sh \| bash` |
| шлюз не стартує | `journalctl -u claude-gateway -n 50 --no-pager`; найчастіше порожній `GATEWAY_TOKENS` або Claude Code не залогінений (крок 4) |
| запит до шлюзу повертає 503 `not_logged_in` | токен із `claude setup-token` не вписано або вписано з пробілами |
| запит до шлюзу повертає 429 `usage_limit` | вичерпано ліміт підписки Claude, зачекати; бот тим часом працює на правилах |
| запит до шлюзу повертає 401 | `GATEWAY_TOKEN` бота не входить до `GATEWAY_TOKENS` шлюзу (кроки 6 і 9) |
| у боті `Conflict: terminated by other getUpdates request` | працює другий бот із тим самим токеном (крок 2) |
| `uv sync --frozen` падає | `git pull` не підтягнув `uv.lock`; перевір `git status` у відповідній теці |
| `tension-pages` падає з `Permission denied (publickey)` або `denied to deploy key` | deploy key не додано або без Allow write access (крок 12) |
