/* Converts a flat list of file paths into a nested tree structure */

export interface TreeNode {
  name: string;
  path: string;
  isDir: boolean;
  children: TreeNode[];
}

export function buildTree(paths: string[]): TreeNode[] {
  const root: TreeNode = { name: "", path: "", isDir: true, children: [] };

  for (const filePath of paths) {
    const parts = filePath.split("/");
    let current = root;

    for (let i = 0; i < parts.length; i++) {
      const part = parts[i]!;
      const isLast = i === parts.length - 1;
      const partPath = parts.slice(0, i + 1).join("/");

      const existing = current.children.find((c) => c.name === part);
      if (existing) {
        current = existing;
      } else {
        const node: TreeNode = {
          name: part,
          path: partPath,
          isDir: !isLast,
          children: [],
        };
        current.children.push(node);
        current = node;
      }
    }
  }

  // Sort: directories first, then alphabetical
  const sortNodes = (nodes: TreeNode[]): TreeNode[] => {
    nodes.sort((a, b) => {
      if (a.isDir !== b.isDir) return a.isDir ? -1 : 1;
      return a.name.localeCompare(b.name);
    });
    for (const node of nodes) {
      if (node.children.length > 0) sortNodes(node.children);
    }
    return nodes;
  };

  return sortNodes(root.children);
}

const EXT_TO_LANG: Record<string, string> = {
  ts: "typescript",
  tsx: "typescript",
  js: "javascript",
  jsx: "javascript",
  py: "python",
  rs: "rust",
  go: "go",
  rb: "ruby",
  java: "java",
  kt: "kotlin",
  swift: "swift",
  c: "c",
  cpp: "cpp",
  h: "c",
  hpp: "cpp",
  cs: "csharp",
  css: "css",
  scss: "scss",
  html: "xml",
  xml: "xml",
  json: "json",
  yaml: "yaml",
  yml: "yaml",
  toml: "ini",
  md: "markdown",
  sql: "sql",
  sh: "bash",
  bash: "bash",
  zsh: "bash",
  dockerfile: "dockerfile",
  tf: "hcl",
  hcl: "hcl",
  lua: "lua",
  vim: "vim",
  makefile: "makefile",
  graphql: "graphql",
  gql: "graphql",
  proto: "protobuf",
};

export function detectLanguage(path: string): string | undefined {
  const filename = path.split("/").pop()?.toLowerCase() ?? "";

  // Special filenames
  if (filename === "dockerfile") return "dockerfile";
  if (filename === "makefile") return "makefile";
  if (filename.endsWith(".tftpl")) return "bash";

  const ext = filename.split(".").pop()?.toLowerCase() ?? "";
  return EXT_TO_LANG[ext];
}
