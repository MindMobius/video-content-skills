import { existsSync, readFileSync } from 'node:fs'
import { homedir } from 'node:os'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

export const name = 'video-subtitle-bundle'
export const inject = ['skills']

const root = fileURLToPath(new URL('../', import.meta.url))
const skillsRoot = join(root, '.agents', 'skills')
const skillNames = [
  'video-subtitle',
  'video-to-content',
  'wechat-draft-handoff',
]

function readSkill(skillName) {
  const path = join(skillsRoot, skillName, 'SKILL.md')
  const source = readFileSync(path, 'utf8')
  const frontmatter = source.match(/^---\r?\n([\s\S]*?)\r?\n---\r?\n?/)
  if (!frontmatter) {
    throw new Error(`video-subtitle-skill: ${path} has no YAML frontmatter`)
  }
  const nameMatch = frontmatter[1].match(/^name:\s*(.+?)\s*$/m)
  const descriptionMatch = frontmatter[1].match(/^description:\s*(.+?)\s*$/m)
  const parsedName = nameMatch?.[1]?.trim().replace(/^['"]|['"]$/g, '')
  const description = descriptionMatch?.[1]?.trim().replace(/^['"]|['"]$/g, '')
  if (parsedName !== skillName || !description) {
    throw new Error(`video-subtitle-skill: invalid metadata in ${path}`)
  }
  return {
    name: parsedName,
    description,
    content: source.slice(frontmatter[0].length),
    source: 'bundled',
    provider: 'video-subtitle-skill',
    resourceBase: {
      kind: 'directory',
      path: dirname(path),
    },
  }
}

function defaultPython() {
  const configured = process.env.VIDEO_SUBTITLE_DSH_PYTHON?.trim()
  if (configured) return configured
  const relative = process.platform === 'win32'
    ? ['.venv', 'Scripts', 'python.exe']
    : ['.venv', 'bin', 'python']
  return join(root, ...relative)
}

function runtimeEnvironment() {
  const config = process.env.VIDEO_SUBTITLE_CONFIG?.trim()
  return config ? { VIDEO_SUBTITLE_CONFIG: config } : {}
}

export function apply(ctx) {
  for (const skillName of skillNames) {
    ctx.skills.register(readSkill(skillName))
  }

  const python = defaultPython()
  ctx.provide('videoSubtitleBundle', Object.freeze({
    root,
    python,
    env: Object.freeze(runtimeEnvironment()),
    ready: existsSync(python),
    bootstrap: Object.freeze({
      command: process.platform === 'win32' ? 'py' : 'python3',
      args: Object.freeze([join(root, 'scripts', 'bootstrap.py'), '--apply']),
      fallbackHome: join(
        process.env.DSH_HOME?.trim() || join(homedir(), '.dsh'),
        'video-subtitle',
      ),
    }),
  }))
}
