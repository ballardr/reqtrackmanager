import base from "./playwright.config";
export default {
  ...base,
  use: { ...base.use, launchOptions: { args: [`--log-net-log=/private/tmp/claude-502/-Users-rballard-git-reqtrackmanager/e7e5aaf9-f41d-4f42-ad60-0ee5fe40094b/scratchpad/netlog/netlog-${process.pid}.json`, "--net-log-capture-mode=Everything"] } },
};
