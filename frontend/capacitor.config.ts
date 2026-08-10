import type { CapacitorConfig } from "@capacitor/cli";

/**
 * Capacitor 配置（手机 App 壳）
 *
 * 当前模式：打包本地构建产物（webDir=dist），App 通过 VITE_API_BASE 连接远程后端。
 * 部署好云服务器后，把 `webDir` 模式切换为直连模式（更省事，同源无 CORS 问题）：
 *
 *   server: { url: "https://你的域名", cleartext: false },
 *   android: { allowMixedContent: false },
 *
 * 切换后 App 就是云端的全屏入口，前端更新只需改服务器，无需重新发版。
 */
const config: CapacitorConfig = {
  appId: "com.novelagent.app",
  appName: "NovelAgent",
  webDir: "dist",
  server: {
    // 注释掉即加载本地 dist；部署后取消注释并填服务器地址
    // url: "https://your-domain.com",
    cleartext: false,
  },
  android: {
    allowMixedContent: false,
  },
};

export default config;
