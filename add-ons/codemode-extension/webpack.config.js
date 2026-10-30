const path = require("path");

module.exports = {
  entry: path.resolve(__dirname, "src/index.tsx"),
  output: {
    filename: "codemode_extension.js",
    path: path.resolve(__dirname, "../../dist"),
  },
  performance: {
    hints: false,
  },
  resolve: {
    extensions: [".tsx", ".ts", ".js"],
  },
  module: {
    rules: [
      {
        test: /\.(ts|tsx|js)$/,
        exclude: /node_modules|dist\/codemode\.js/,
        use: {
          loader: "babel-loader",
          options: {
            presets: [
              ["@babel/preset-env", { targets: "defaults" }],
              ["@babel/preset-react", { runtime: "automatic" }],
              "@babel/preset-typescript",
            ],
          },
        },
      },
    ],
  },
  devServer: {
    port: 8080,
    allowedHosts: "all",
    headers: {
      "Access-Control-Allow-Origin": "*",
      "Access-Control-Allow-Methods": "*",
      "Access-Control-Allow-Headers": "*",
    },
  },
};
