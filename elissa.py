#!/usr/bin/env python3

import sys, os
from deltabot_cli import BotCli
from deltachat2 import EventType, MsgData, events

cli = BotCli("elissa")

@cli.on_start
def on_start(bot, args):
    if not args.script: exit("The --script option is mandatory with serve")
    with open(args.script) as f:
        bot.script = f.read()
    try:
        _ = parse_script(bot.script)
    except Exception as e:
        exit(e)
    bot.logger.info(f"Script file '{args.script}' read without errors")
    # TODO: Start some kind of background thread that monitors some place
    # where wait commands can be queued. Maybe also using inotify? The
    # background thread should then execute those wait commands once
    # the time to do so has come. Afterwards, the background thread also
    # needs to advance the relevant execution pointer so that that chat
    # is no longer blocked.

@cli.on(events.RawEvent)
def log_event(bot, accid, event):
    if event.kind == EventType.INFO:
        bot.logger.debug(event.msg)
    elif event.kind == EventType.WARNING:
        bot.logger.warning(event.msg)
    elif event.kind == EventType.ERROR:
        bot.logger.error(event.msg)
    elif event.kind == EventType.MSG_DELIVERED:
        bot.rpc.delete_messages(accid, [event.msg_id])
    elif event.kind == EventType.SECUREJOIN_INVITER_PROGRESS:
        if event.progress == 1000 \
                and not bot.rpc.get_contact(accid, event.contact_id).is_bot:
            # Bot's QR scanned by an user. This could be a new chat.
            chatid = bot.rpc.create_chat_by_contact_id(accid, event.contact_id)
            userdir = f"chats/a{accid}c{chatid}"
            if os.path.isdir(userdir):
                bot.logger.info(f"Recreated chat '{userdir}'")
                return
            _ensure_userdir(bot, userdir)
            with open(f"{userdir}/script.txt") as f:
                script = parse_script(f.read())
            if len(script) > 0 and script[0]["command"] == "":
                reply = MsgData(text=script[0]["reply"])
                log_message(userdir, reply)
                bot.rpc.send_msg(accid, chatid, reply)
                with open(f"{userdir}/instruction_pointer.txt", "w") as f:
                    print(1, file=f)
            bot.logger.info(f"Created new chat '{userdir}'")

def _ensure_userdir(bot, userdir: str) -> None:
    """
    Ensure that the userdir exists. If it does not exist yet, it is
    initialized.
    """
    if os.path.isdir(userdir): return
    os.makedirs(userdir)
    with open(f"{userdir}/script.txt", "w") as f:
        f.write(bot.script)
    with open(f"{userdir}/instruction_pointer.txt", "w") as f:
        print(0, file=f)

@cli.on(events.NewMessage)
def handle_message(bot, accid, event):
    userdir = f"chats/a{accid}c{event.msg.chat_id}"
    _ensure_userdir(bot, userdir)
    log_message(userdir, event.msg)
    with open(f"{userdir}/instruction_pointer.txt") as f:
        pointer = int(f.read())
    with open(f"{userdir}/script.txt") as f:
        script = parse_script(f.read())
    if pointer >= len(script):
        bot.logger.info("No instructions left in script")
        return
    inst = script[pointer]
    if inst["command"] == "wait-for":
        if event.msg.view_type.lower() != inst["args"][0] \
                    or ("match" in inst and \
                    event.msg.text.split() != inst["match"]):
            if "otherwise" in inst and inst["otherwise"]:
                reply = MsgData(text=" ".join(inst["otherwise"]))
                bot.rpc.send_msg(accid, event.msg.chat_id, reply)
                log_message(userdir, reply)
            return
    elif inst["command"] == "wait":
        # We are currently executing a wait command. Therefore, we ignore
        # all incoming messages at this stage, possibly executing an
        # "otherwise" action in the process. After the wait command is
        # done, the execution pointer will be advanced independently of
        # incoming messages (see below).
        if "otherwise" in inst and inst["otherwise"].strip():
            reply = MsgData(text=inst["otherwise"])
            bot.rpc.send_msg(accid, msg.chat_id, reply)
            log_message(userdir, reply)
        return
    else:
        # If we encounter an unknown command at this point, we log an
        # error and proceed as if the command was successful. Note that
        # this code path should be dead since the script is validated
        # when it is read.
        c = inst["command"]
        bot.logger.error(
            f"Unknown command '{c}' found in script at instruction {pointer}."
        )
    # Since we did not return early, the instruction seems to have worked.
    if inst["reply"].strip():
        reply = MsgData(text=inst["reply"])
        bot.rpc.send_msg(accid, event.msg.chat_id, reply)
        log_message(userdir, reply)
    if pointer+1 >= len(script):
        # TODO: This was the last instruction. If any action is to be
        # taken after the last instruction, take that action here!
        pass
    elif script[pointer+1]["command"] == "wait":
        # TODO: The next command is a wait command. The execution of
        # that command must be scheduled and the run independently of
        # incoming messages. Afterwards, the pointer must be advanced
        # as well so that incoming messages can again trigger actions.
        # Until the pointer advances beyond the wait command, all incoming
        # messages will be ignored (see above).
        #
        # Valid units of time for the wait command are sec, min, h and
        # d. The first argument must be an integer.
        pass
    with open(f"{userdir}/instruction_pointer.txt", "w") as f:
        print(pointer+1, file=f)

def log_message(userdir: str, message) -> None:
    with open(f"{userdir}/conversation_log.txt", "a") as f:
        print(message, file=f)

def parse_command(command: str) -> dict:
    result = {}
    if not command.startswith('%'):
        raise Exception('Commands must start with "%"')
    context = "start"
    for word in command[1:].strip().split():
        if context == "start":
            result["command"] = word
            context = "args"
            result[context] = []
        elif word == "%match%":
            context = "match"
            result[context] = []
        elif word == "%otherwise%":
            context = "otherwise"
            result[context] = []
        else:
            result[context].append(word)
    return result

def validate_script(parsed_script: list[dict]) -> None:
    # Validate the script semantics; otherwise raise an exception
    for i, inst in enumerate(parsed_script):
        # Check that "command" and "reply" exist.
        if not "command" in inst:
            raise Exception(f"Instruction {i} has no command")
        if not "reply" in inst:
            raise Exception(f"Instruction {i} has no reply")
        # Check that command is within a known set of commands and has
        # the expected arguments.
        if inst["command"] == "":
            pass    # This is allowed and results in the greeting message.
        elif inst["command"] == "wait-for":
            if len(inst["args"]) != 1:
                raise Exception(f"Error at instruction {i}: "\
                                 "wait-for takes exactly one argument")
            if inst["args"][0] not in ["text", "voice", "image"]:
                raise Exception(f"Error at instruction {i}: "\
                                 "the type must be text, voice or image")
            if "match" in inst and inst["args"][0] != "text":
                raise Exception(f"Error at instruction {i}: "\
                                 "%match% is only allowed with wait-for text")
        elif inst["command"] == "wait":
            if len(inst["args"]) != 2:
                raise Exception(f"Error at instruction {i}: "\
                                 "wait takes exactly two arguments")
            elif inst["args"][1] not in ["sec", "min", "h", "d"]:
                raise Exception(f"Error at instruction {i}: "\
                                 "the type unit be sec, min, h or d")
            try:
                _ = int(inst["args"][0])
            except Exception:
                arg0 = inst["args"][0]
                raise Exception(f"Error at instruction {i}: "\
                                f"unable to parse '{arg0}' as an integer")
        else:
            c = inst["command"]
            raise Exception(f"Unknown command '{c}' found at instruction {i}")

def parse_script(script: str):
    result = []; textblock = ""; command = None
    for line in script.splitlines():
        if line.lstrip().startswith('%'):
            if command or textblock:
                if not command: command = {"command": ""}
                result.append({
                    **command, "reply": textblock.strip(),
                })
            textblock = ""; command = parse_command(line.lstrip())
        else:
            textblock += line
    if command or textblock:
        result.append({
            **command, "reply": textblock.strip(),
        })
    validate_script(result)
    return result

if __name__ == "__main__":
    cli.add_generic_option("--script",
                           help="Filename of the elissa script to use")
    try:
        cli.start()
    except KeyboardInterrupt:
        pass
