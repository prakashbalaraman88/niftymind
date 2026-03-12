const { getDefaultConfig } = require("expo/metro-config");

const config = getDefaultConfig(__dirname);

config.resolver.blockList = [
  /firebase.*_tmp_\d+/,
  /messaging-compat_tmp_\d+/,
];

module.exports = config;
