import { defineRailway, preserve, project, service, volume } from "railway/iac";

export default defineRailway(() => {
  const amexRemindersVolume = volume("amex-reminders-volume", { alerts: { usage: { "100": {}, "80": {}, "95": {} } }, allowOnlineResize: true, region: "asia-southeast1-eqsg3a", sizeMB: 50000 });
  const amexReminders = service("amex-reminders", {
    build: { builder: "NIXPACKS", nixpacksPlan: { phases: { setup: { nixPkgs: ["python312"] } } } },
    deploy: {
      startCommand: "uvicorn app.main:app --host 0.0.0.0 --port $PORT --no-access-log --log-config uvicorn-log-config.json",
      restartPolicyType: "ON_FAILURE",
      restartPolicyMaxRetries: 3,
    },
    replicas: { "asia-southeast1-eqsg3a": 1 },
    volumeMounts: {
      "/data": amexRemindersVolume,
    },
    env: {
      ABUSE_HASH_SALT: preserve(),
      ALERT_EXPORT_TOKEN: preserve(),
      ALLOWED_ORIGIN: preserve(),
      BRAVE_API_KEY: preserve(),
      CONFIRM_TOKEN_EXPIRY_HOURS: preserve(),
      DB_PATH: preserve(),
      GEMINI_API_KEY: preserve(),
      GITHUB_DISPATCH_TOKEN: preserve(),
      OWNER_ALERTS_ENABLED: preserve(),
      OWNER_ALERT_INGEST_TOKEN: preserve(),
      OWNER_ALERT_NOT_BEFORE: preserve(),
      PUBLIC_BASE_URL: preserve(),
      RESEND_API_KEY: preserve(),
      RESEND_FROM: preserve(),
      SUBSCRIBE_EMAIL_LIMIT: preserve(),
      SUBSCRIBE_GLOBAL_LIMIT: preserve(),
      SUBSCRIBE_IP_LIMIT: preserve(),
      TELEGRAM_BOT_TOKEN: preserve(),
      TELEGRAM_GUIDE_BOT_TOKEN: preserve(),
      TELEGRAM_GUIDE_ENABLED: preserve(),
      TELEGRAM_GUIDE_LLM_ENABLED: preserve(),
      TELEGRAM_GUIDE_WEBHOOK_SECRET: preserve(),
      TELEGRAM_IDENTITY_HASH_SALT: preserve(),
      TELEGRAM_OWNER_CHAT_ID: preserve(),
      TELEGRAM_REMINDERS_ENABLED: preserve(),
      TELEGRAM_REMINDER_DISPATCH_TOKEN: preserve(),
      TFT_LIVE_REFRESH_ENABLED: preserve(),
      TFT_LIVE_REFRESH_INTERVAL_SECONDS: preserve(),
      TFT_LIVE_SINGLE_REPLICA_CONFIRMED: preserve(),
      TRUSTED_PROXY_HOPS: preserve(),
    },
  });

  return project("amex-reminders", {
    resources: [amexReminders, amexRemindersVolume],
  });
});
