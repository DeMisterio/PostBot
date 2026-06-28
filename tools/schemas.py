PLANNING_TOOLS = [
  {
    "type": "function",
    "function": {
      "name": "get_author_profile",
      "description": "Вернуть полный профиль автора: голос, правила, бэкграунд, настройки цикла.",
      "parameters": {"type": "object", "properties": {}, "additionalProperties": False}
    }
  },
  {
    "type": "function",
    "function": {
      "name": "get_posts_history",
      "description": "Вернуть список уже опубликованных постов (тема, тип, источник, дата, summary, базовая статистика).",
      "parameters": {
        "type": "object",
        "properties": {
          "limit": {"type": "integer", "description": "Сколько последних постов вернуть, по умолчанию 30"}
        },
        "additionalProperties": False
      }
    }
  },
  {
    "type": "function",
    "function": {
      "name": "list_github_repos",
      "description": "Получить список репозиториев автора с метаданными (имя, описание, язык, дата последнего коммита, наличие README, видимость).",
      "parameters": {"type": "object", "properties": {}, "additionalProperties": False}
    }
  },
  {
    "type": "function",
    "function": {
      "name": "get_github_readme",
      "description": "Получить содержимое README.md конкретного репозитория, чтобы оценить, достаточно ли там материала для поста.",
      "parameters": {
        "type": "object",
        "properties": {
          "repo_full_name": {"type": "string", "description": "owner/repo"}
        },
        "required": ["repo_full_name"],
        "additionalProperties": False
      }
    }
  },
  {
    "type": "function",
    "function": {
      "name": "submit_plan",
      "description": "Terminal tool. Отправить итоговый план цикла на согласование автору. Вызывается один раз, в конце рассуждения.",
      "parameters": {
        "type": "object",
        "properties": {
          "items": {
              "type": "array", 
              "description": "Массив пунктов плана",
              "items": {
                  "type": "object",
                  "properties": {
                      "type": {"type": "string"},
                      "title": {"type": "string"},
                      "source": {
                          "type": "object",
                          "properties": {
                              "kind": {"type": "string"},
                              "repo_full_name": {"type": "string"},
                              "readme_ref": {"type": "string"}
                          }
                      },
                      "planned_date": {"type": "string", "description": "ISO8601 (YYYY-MM-DDTHH:MM:SSZ)"},
                      "notes": {"type": "string"}
                  },
                  "required": ["type", "title", "source", "planned_date", "notes"]
              }
          }
        },
        "required": ["items"],
        "additionalProperties": False
      }
    }
  }
]

GENERATION_TOOLS = [
  {
    "type": "function",
    "function": {
      "name": "get_plan_item",
      "description": "Получить конкретный пункт плана, для которого сейчас идёт генерация (type, title, source, notes).",
      "parameters": {"type": "object", "properties": {}, "additionalProperties": False}
    }
  },
  {
    "type": "function",
    "function": {
      "name": "get_github_readme",
      "description": "Получить содержимое README.md репозитория, указанного в source пункта плана.",
      "parameters": {
        "type": "object",
        "properties": { "repo_full_name": {"type": "string"} },
        "required": ["repo_full_name"],
        "additionalProperties": False
      }
    }
  },
  {
    "type": "function",
    "function": {
      "name": "get_github_repo_metadata",
      "description": "Получить описание, язык, даты последних коммитов репозитория — для случаев, когда README отсутствует или скудный.",
      "parameters": {
        "type": "object",
        "properties": { "repo_full_name": {"type": "string"} },
        "required": ["repo_full_name"],
        "additionalProperties": False
      }
    }
  },
  {
    "type": "function",
    "function": {
      "name": "get_recent_posts",
      "description": "Получить последние 3-5 опубликованных постов, чтобы не повторять структуру и формулировки.",
      "parameters": {"type": "object", "properties": {}, "additionalProperties": False}
    }
  },
  {
    "type": "function",
    "function": {
      "name": "ask_author",
      "description": "Задать автору уточняющий вопрос в чат (например, нужна ли фотография к посту) и ожидать ответа.",
      "parameters": {
        "type": "object",
        "properties": { "question": {"type": "string"} },
        "required": ["question"],
        "additionalProperties": False
      }
    }
  },
  {
    "type": "function",
    "function": {
      "name": "propose_post",
      "description": "Передать готовый текст поста автору на согласование через кнопки. Не публикует напрямую.",
      "parameters": {
        "type": "object",
        "properties": {
          "post_text": {"type": "string"},
          "need_image": {"type": "boolean"},
          "image_prompt_or_request": {"type": ["string", "null"]}
        },
        "required": ["post_text", "need_image"],
        "additionalProperties": False
      }
    }
  },
  {
    "type": "function",
    "function": {
      "name": "publish_post",
      "description": "Terminal tool с побочным эффектом. Публикует пост в канал.",
      "parameters": {
        "type": "object",
        "properties": {
          "plan_item_id": {"type": "string"},
          "post_text": {"type": "string"},
          "image_ref": {"type": ["string", "null"], "description": "file_id или null"}
        },
        "required": ["plan_item_id", "post_text"],
        "additionalProperties": False
      }
    }
  }
]

CHAT_TOOLS = [
  {
    "type": "function",
    "function": {
      "name": "get_author_profile",
      "description": "Вернуть полный профиль автора",
      "parameters": {"type": "object", "properties": {}, "additionalProperties": False}
    }
  },
  {
    "type": "function",
    "function": {
      "name": "get_current_plan",
      "description": "Получить текущий content_plan со статусами всех пунктов.",
      "parameters": {"type": "object", "properties": {}, "additionalProperties": False}
    }
  },
  {
    "type": "function",
    "function": {
      "name": "get_posts_history",
      "description": "Вернуть список уже опубликованных постов",
      "parameters": {
          "type": "object", 
          "properties": {"limit": {"type": "integer"}},
          "additionalProperties": False
      }
    }
  },
  {
    "type": "function",
    "function": {
      "name": "get_pending_post_state",
      "description": "Узнать, есть ли сейчас пост, ожидающий решения автора, и сколько времени он уже ждёт.",
      "parameters": {"type": "object", "properties": {}, "additionalProperties": False}
    }
  },
  {
    "type": "function",
    "function": {
      "name": "propose_patch",
      "description": "Terminal tool. Предложить автору структурированное изменение content_plan или author_profile.",
      "parameters": {
        "type": "object",
        "properties": {
          "target": {"type": "string", "enum": ["content_plan", "author_profile"]},
          "patch": {
              "type": "object", 
              "description": "Объект с изменениями. Для профиля автора используйте ключи: 'voice_and_rules', 'background', 'schedule_settings'.",
              "properties": {
                  "voice_and_rules": {"type": "object", "description": "Словарь: правила текста, тон (tone of voice), форматирование"},
                  "background": {"type": "object", "description": "Словарь: биография автора, фокус канала, стек технологий"},
                  "schedule_settings": {"type": "object", "description": "Словарь: частота и расписание постов"}
              },
              "additionalProperties": True
          },
          "human_summary": {"type": "string", "description": "Короткое описание изменения для показа автору"}
        },
        "required": ["target", "patch", "human_summary"],
        "additionalProperties": False
      }
    }
  }
]
