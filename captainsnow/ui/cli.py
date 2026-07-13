import sys
import os
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

import click
import asyncio
from rich.console import Console
from rich.spinner import Spinner
from core.orchestrator import CaptainOrchestrator
from core.profile import load_config

console = Console()

async def run_with_spinner(coro, message="Working"):
    with console.status(f"[bold green]{message}...") as status:
        result = await coro
    return result

@click.group()
def cli():
    pass

@cli.command()
@click.argument('message', nargs=-1)
def chat(message):
    """General-purpose assistant chat."""
    config = load_config()
    captain = CaptainOrchestrator(config)
    user_input = ' '.join(message)
    final = asyncio.run(run_with_spinner(captain.process_request(user_input), "CaptainSnow is thinking"))
    console.print(final)

@cli.command()
@click.option('--audit', 'url', help='Run SEO audit on a URL')
def seo(url):
    """Hyper-focused SEO mode."""
    config = load_config()
    captain = CaptainOrchestrator(config)
    task = {'action': 'audit', 'url': url}
    result = asyncio.run(run_with_spinner(captain.skills['seo_core'].execute(task), "Running SEO Audit"))
    console.print(result)

@cli.command()
@click.option('--type', 'agent_type', help='Agent type: browser, search, etc. — any enabled skill name.')
@click.option('--task', 'task_description')
def agent(agent_type, task_description):
    """Invoke a specific agent directly."""
    config = load_config()
    captain = CaptainOrchestrator(config)
    if agent_type in captain.skills:
        task = {'action': 'execute', 'prompt': task_description}
        result = asyncio.run(run_with_spinner(captain.skills[agent_type].execute(task), f"Running {agent_type} agent"))
        console.print(result)
    else:
        console.print(f"[red]Skill '{agent_type}' is not enabled or does not exist.[/red]")

@cli.command()
def monitor():
    """Start the proactive monitoring daemon."""
    from skills.watchers import MonitoringDaemon
    config = load_config()
    daemon = MonitoringDaemon(config)
    daemon.run()

@cli.command()
def serve():
    """Run the FastAPI web UI + Telegram bot together (used by Docker CMD)."""
    from captainsnow.ui.serve import main as serve_main
    serve_main()

def main():
    cli()

if __name__ == '__main__':
    cli()
