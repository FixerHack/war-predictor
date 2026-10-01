# Інструкція для агента: розгортання Tension Index на сервері

Цей документ — для Claude Code (або іншого агента), який працює на комп'ютері власниці проєкту й має SSH-доступ до сервера. Мета: розгорнути бота, таймери збору даних і шлюз Claude Code на сервері та переконатися, що все працює.

Пиши власниці українською й не звертайся до неї на ім'я.

## Правила

1. **Секрети не друкуй.** Токени з `.env` (Telegram, `CLAUDE_CODE_OAUTH_TOKEN`, `GATEWAY_TOKENS`) не виводь у чат, не логуй і не передавай аргументами команд, які потрапляють в історію shell. Переносячи `.env`, копіюй файл (`scp`) або перевіряй лише, що рядок не порожній (`grep -c '^KEY=.\+'`).
2. **Перед руйнівними чи незворотними діями питай.** Сюди входять видалення файлів чи баз, перевстановлення системи, зміни фаєрволу, відкриття портів назовні, перезапуск чужих сервісів і `apt upgrade` усієї системи. Встановлення наших залежностей і запуск `scripts/install_server.sh` дозволені.
3. **Порти назовні не відкривай.** Шлюз слухає лише `127.0.0.1:8787`. HTTPS-проксі для доступу ззовні — окремий крок, лише за явною згодою власниці.
4. **Не запускай два боти з одним токеном Telegram.** Перед стартом бота на сервері зупини локальний (див. крок 2).
5. **Не змінюй код у репозиторії.** Якщо скрипт падає через помилку в коді, опиши її (команда, вивід, гіпотеза) і зупинись, без латок на сервері.
6. **Звітуй коротко після кожного етапу:** що зроблено, що перевірено, що далі.

## Що потрібно від власниці

Спитай, якщо цього немає:
- **SSH-доступ:** `користувач@адреса` (і порт, якщо не 22). Користувач має мати `sudo`.
- **ОС сервера:** підтримуються Debian та Ubuntu із systemd. Перевір сам: `cat /etc/os-release`.
- **Згода** на те, щоб перенести локальний `.env` проєкту на сервер.

## Кроки

### 1. Перевірка доступу й сервера

```bash
ssh USER@HOST 'cat /etc/os-release | head -3; id; sudo -n true && echo SUDO_OK || echo SUDO_NEEDS_PASSWORD; systemctl --version | head -1; df -h ~ | tail -1; free -h | head -2'
```

Що має бути:
- ОС Debian або Ubuntu;
- є systemd;
- щонайменше 2 ГБ вільного диска і 1 ГБ RAM.

Якщо `sudo` питає пароль, команди з `sudo` власниця вводитиме сама: дай їй точну команду. Пароль у чат не проси.

### 2. Зупинити локальний бот

Локально, у теці проєкту на Mac:

```bash
pkill -f "tension-index bot" || true
```

Якщо бот запущено в іншому терміналі, попроси власницю натиснути там Ctrl+C.

### 3. Код на сервері

```bash
ssh USER@HOST 'command -v git >/dev/null || sudo apt-get install -y git curl python3'
ssh USER@HOST 'test -d ~/war-predictor && (cd ~/war-predictor && git pull --ff-only) || git clone https://github.com/FixerHack/war-predictor.git ~/war-predictor'
```

Якщо `git clone` питає логін, репозиторій приватний. Зупинись і попроси власницю зробити його публічним або додати на сервер deploy key (GitHub → репозиторій → Settings → Deploy keys).

### 4. Перший запуск і `.env`

```bash
ssh USER@HOST 'cd ~/war-predictor && ./scripts/install_server.sh'
```

Перший запуск створює `.env` і зупиняється. Тепер скопіюй значення з локального `.env` на сервер, з дозволу власниці. Найпростіше взяти потрібні рядки з локального файлу й вписати їх у серверний, нічого не друкуючи. Скрипт нижче запускай у теці проєкту на Mac:

```bash
for key in TELEGRAM_BOT_TOKEN TELEGRAM_CHAT_ID TELEGRAM_ADMIN_IDS HEALTH_PING_URL; do
  line="$(grep -E "^${key}=" .env | tail -1)"
  [ -n "$line" ] && printf '%s\n' "$line" | ssh USER@HOST "cd ~/war-predictor && key=${key} && grep -v \"^\${key}=\" .env > .env.tmp; cat >> .env.tmp; mv .env.tmp .env; chmod 600 .env"
done
ssh USER@HOST 'cd ~/war-predictor && for k in TELEGRAM_BOT_TOKEN TELEGRAM_CHAT_ID TELEGRAM_ADMIN_IDS; do printf "%s: " $k; grep -c "^$k=.\+" .env; done'
```

Кожен ключ має показати `1`.

На сервері не треба переносити:
- `CLASSIFIER_PROVIDER` — на сервері він `gateway`, і скрипт ставить це сам;
- `DATABASE_PATH` — база на сервері своя, і скрипт ініціалізує її сам.

### 5. Повне встановлення

```bash
ssh -t USER@HOST 'cd ~/war-predictor && ./scripts/install_server.sh'
```

`-t` потрібен, щоб `sudo` міг спитати пароль. Скрипт:
- встановлює uv, залежності, Claude Code (`~/.local/bin/claude`) і шлюз;
- генерує токен шлюзу й прописує його в обидва `.env`;
- встановлює й вмикає юніти systemd.

У кінці він друкує статус юнітів і результат healthcheck.

### 6. Вхід Claude Code на сервері

Шлюз стартує лише тоді, коли Claude Code на сервері залогінений. Попроси власницю виконати на своєму Mac:

```bash
claude setup-token
```

Команда відкриє браузер і надрукує довгий токен. Попроси власницю **самій** вписати його на сервері, щоб токен не проходив через чат:

```bash
ssh -t USER@HOST 'cd ~/war-predictor && nano gateway/.env'   # рядок CLAUDE_CODE_OAUTH_TOKEN=...
```

Потім перевір і запусти скрипт ще раз:

```bash
ssh USER@HOST 'cd ~/war-predictor && grep -c "^CLAUDE_CODE_OAUTH_TOKEN=.\+" gateway/.env'   # має бути 1
ssh -t USER@HOST 'cd ~/war-predictor && ./scripts/install_server.sh'
```

### 7. Перевірка

```bash
ssh USER@HOST 'systemctl is-active tension-bot claude-gateway; systemctl list-timers "tension-*" --no-pager | head -12'
ssh USER@HOST 'curl -fsS http://127.0.0.1:8787/health'
ssh USER@HOST 'cd ~/war-predictor/gateway && set -a && . ./.env && set +a && curl -s -m 60 http://127.0.0.1:8787/v1/complete -H "Authorization: Bearer ${GATEWAY_TOKENS%%,*}" -H "Content-Type: application/json" -d "{\"prompt\":\"Reply with OK\"}" | head -c 300'
ssh USER@HOST 'cd ~/war-predictor && ./scripts/run.sh run 2>&1 | tail -15'
ssh USER@HOST 'cd ~/war-predictor && ./scripts/healthcheck.sh; echo exit=$?'
ssh USER@HOST 'journalctl -u tension-bot -n 30 --no-pager'
```

Що має бути:
- обидва сервіси `active`;
- `/health` повертає `{"ok":true,...}`;
- тестовий запит до шлюзу повертає `"text":"OK"`;
- у `run` є рядки `claude CLI call ...: ok` або `classified: ... 'claude': N` з N > 0, а в кінці `scores: 38/38 published`;
- healthcheck завершується з `exit=0` (OK) або `1` (WARN, допустимо в першу добу);
- у логах бота немає помилок, а `/start` у Telegram показує дашборд. Попроси власницю перевірити.

### 8. Звіт

Наприкінці дай власниці короткий звіт:
- що встановлено й працює (сервіси, таймери, шлюз);
- результат перевірок з кроку 7;
- що лишилось за нею (наприклад, HTTPS для шлюзу ззовні, `HEALTH_PING_URL`, захист `main` на GitHub);
- як оновлювати: `ssh USER@HOST 'cd ~/war-predictor && ./scripts/deploy.sh'`;
- як дивитися логи: `journalctl -u tension-bot -f`, `journalctl -u claude-gateway -f`.

## Типові проблеми

| Симптом | Що робити |
|---|---|
| `TELEGRAM_BOT_TOKEN is empty in .env` | крок 4 не завершено |
| `claude not found after install` | `ssh USER@HOST 'ls ~/.local/bin; echo $PATH'`, встановити вручну: `curl -fsSL https://claude.ai/install.sh \| bash` |
| шлюз не відповідає | `journalctl -u claude-gateway -n 50 --no-pager`; найчастіше порожній `GATEWAY_TOKENS` або Claude Code не залогінений (крок 6) |
| запит до шлюзу повертає 503 `not_logged_in` | токен із `claude setup-token` не вписано або вписано з пробілами |
| запит до шлюзу повертає 429 `usage_limit` | вичерпано ліміт підписки Claude, зачекати; бот тим часом працює на правилах |
| у боті `Conflict: terminated by other getUpdates request` | працює другий бот із тим самим токеном (крок 2) |
| `uv sync --frozen` падає | `git pull` не підтягнув `uv.lock`; перевір `git status` на сервері |
