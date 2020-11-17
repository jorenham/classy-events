# Classy Events

Pythonic event-driven programming.

## Dependencies

Python 3.8, 3.9

## Install

```bash
pip install classy-events
```

## Usage

The main ingredient is an *event handler* instance:

```python
from classy_events import EventHandler
event_handler = EventHandler()
```

You can register *event listeners* for *events* of any type.
In this example we use string events.
An event listener is a callable, like a function or a method. 
The registered event handlers for a specific event are called if 
that event is dispatched by the event handler. 
Any keyword arguments that accompany the event are passed to the event 
listeners. 

### Function listeners

The listener for the event `"spam"`, no callbacks needed!

```python
@event_handler.on("spam")
def spam(value):
    print(f"on 'spam': '{value}'")
```

When the `"spam"` event is dispatched from anywhere in the code, `def spam` will be called:

```jupyterpython
event_handler.dispatch("spam", value="ham and eggs")
```

Now `on 'spam': 'ham and eggs'` is printed.

### Classy listeners

To use instance methods as listeners, only one extra step is needed:

```python
class Spam:
    def __init__(self):
        event_handler.bind(self)

    @event_handler.on("classy_spam")
    def spam(self, value):
        print(f"on '{type(self).__name__}.spam': '{value}'")

spam_instance = Spam()
```

In `__init__`, the instance is bound to the handler. Note that this 
`event_handler.bind` call is not required to be within the `__init__`.

To see this in action, we dispatch the `"classy_spam"` event:

```python
event_handler.dispatch("classy_spam", value="the classiest")
```

And we see the output `on 'Spam.spam': 'the classiest'`.
