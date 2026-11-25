"""Pipeline de geração: cada etapa recebe um Ctx com o job, o canal e a configuração."""

from .core import *  # noqa: F401,F403
from .writing import *  # noqa: F401,F403
from .media import *  # noqa: F401,F403
from .assembly import *  # noqa: F401,F403
from .clips import *  # noqa: F401,F403
from .runner import *  # noqa: F401,F403
