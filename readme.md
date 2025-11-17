# Elissa

Elissa is a chatbot interpreter that relies on the [Delta Chat
Bot API](https://bots.delta.chat/) for message delivery, end-to-end
encryption, and related matters. The specific behaviour of an elissa-based
chatbot is scripted using a custom scripting language. A basic elissa
script might look like this:

    Greetings, fellow being. What's on your mind?
    % wait-for text
    Thank you for sharing. Goodbye.

Lines starting with `%` are treated as special commands, while everything
else is treated as messages that should be sent to the user. In the
example above, there are two short messages separated by a single
`wait-for text` command. This means that for each new contact, the chatbot
would initiate the conversation by sending the first message, then wait
for a single reply, and then send the second and final message. For a
more elaborate example that also showcases a wider range of commands
please refer to the script named `testbot.txt`.

## Quickstart

    python3 -m pip install --user deltabot-cli
    ./elissa.py -c. init DCACCOUNT:https://nine.testrun.org/new
    ./elissa.py -c. config displayname "Elissa Testbot"
    ./elissa.py -c. link
    ./elissa.py -c. --script=testbot.txt serve

## Dependencies

* [deltabot-cli](https://github.com/deltachat-bot/deltabot-cli-py)

## License

All files in this repository are made available under the terms of the
GNU General Purpose License, version 3 or later. A copy of that license
is included in the repository as `license.txt`.
