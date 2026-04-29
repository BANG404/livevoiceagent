# Server-side quickstart for Programmable Voice

This quickstart shows you how to build a server-side application that makes and receives phone calls. The code in this quickstart makes an outbound call with the [Twilio Voice API](/docs/voice/api) and it handles an inbound call with [text-to-speech](/docs/voice/twiml/say).

## Complete the prerequisites

Select your programming language and complete the prerequisites:

## Python

* [Install Python 3.3 or later](https://www.python.org/downloads/).
* [Install and set up ngrok](https://ngrok.com/docs/getting-started/).
* Install [Flask](http://flask.pocoo.org/) and [Twilio's Python SDK](https://github.com/twilio/twilio-python). To install using [pip](https://pip.pypa.io/en/latest/), run:

  ```bash
  pip install flask twilio
  ```
* [Create a Twilio account](https://www.twilio.com/try-twilio).
* [Buy a voice-enabled phone number](https://www.twilio.com/console/phone-numbers/search).

## Node.js

* [Install Node.js 14 or later](https://nodejs.org/).
* [Install and set up ngrok](https://ngrok.com/docs/getting-started/).
* Install [Express](https://expressjs.com/) and the [Twilio Node.js SDK](https://github.com/twilio/twilio-node):

  ```bash
  npm install twilio express
  ```
* [Create a Twilio account](https://www.twilio.com/try-twilio).
* [Buy a voice-enabled phone number](https://www.twilio.com/console/phone-numbers/search).

## PHP

* [Install PHP 7.2 or later](http://php.net/manual/en/install.php).
* [Install and set up ngrok](https://ngrok.com/docs/getting-started/).
* Install dependencies with Composer:

  1. [Install Composer](https://getcomposer.org/doc/00-intro.md) globally.
  2. Install the [Twilio PHP SDK](https://github.com/twilio/twilio-php):

     ```bash
     composer require twilio/sdk
     ```
* [Create a Twilio account](https://www.twilio.com/try-twilio).
* [Buy a voice-enabled phone number](https://www.twilio.com/console/phone-numbers/search).

## C#/.NET

* [Install .NET 3.5 or later](https://dotnet.microsoft.com/en-us/download).
* [Install and set up ngrok](https://ngrok.com/docs/getting-started/).
* [Create a Twilio account](https://www.twilio.com/try-twilio).
* [Buy a voice-enabled phone number](https://www.twilio.com/console/phone-numbers/search).

## Java

* [Install Java 8 or later](https://www.oracle.com/java/technologies/downloads/).
* [Install and set up ngrok](https://ngrok.com/docs/getting-started/).
* [Install Gradle](https://gradle.org/install/).
* [Create a Twilio account](https://www.twilio.com/try-twilio).
* [Buy a voice-enabled phone number](https://www.twilio.com/console/phone-numbers/search).

## Go

* [Install Go 1.18 or later](https://go.dev/doc/install).
* [Install and set up ngrok](https://ngrok.com/docs/getting-started/).
* [Create a Twilio account](https://www.twilio.com/try-twilio).
* [Buy a voice-enabled phone number](https://www.twilio.com/console/phone-numbers/search).

## Ruby

* [Install Ruby 2.6 or later](https://www.ruby-lang.org/en/documentation/installation/).
* [Install and set up ngrok](https://ngrok.com/docs/getting-started/).
* [Create a Twilio account](https://www.twilio.com/try-twilio).
* [Buy a voice-enabled phone number](https://www.twilio.com/console/phone-numbers/search).

## Set environment variables

Follow these steps to get your Twilio account credentials and set them as environment variables.

## macOS Terminal

1. Go to the [Twilio Console](https://www.twilio.com/console).
2. Copy your **Account SID** and set it as an environment variable using the following command. Replace *YOUR\_ACCOUNT\_SID* with your actual Account SID.
   ```bash
   export TWILIO_ACCOUNT_SID=YOUR_ACCOUNT_SID
   ```
3. Copy your **Auth Token** and set it as an environment variable using the following command. Replace *YOUR\_AUTH\_TOKEN* with your actual Auth Token.
   ```bash
   export TWILIO_AUTH_TOKEN=YOUR_AUTH_TOKEN
   ```

## Windows command line

1. Go to the [Twilio Console](https://www.twilio.com/console).
2. Copy your **Account SID** and set it as an environment variable using the following command. Replace *YOUR\_ACCOUNT\_SID* with your actual Account SID.
   ```bash
   set TWILIO_ACCOUNT_SID=YOUR_ACCOUNT_SID
   ```
3. Copy your **Auth Token** and set it as an environment variable using the following command. Replace *YOUR\_AUTH\_TOKEN* with your actual Auth Token.
   ```bash
   set TWILIO_AUTH_TOKEN=YOUR_AUTH_TOKEN
   ```

## PowerShell

1. Go to the [Twilio Console](https://www.twilio.com/console).
2. Copy your **Account SID** and set it as an environment variable using the following command. Replace *YOUR\_ACCOUNT\_SID* with your actual Account SID.
   ```bash
   $Env:TWILIO_ACCOUNT_SID="YOUR_ACCOUNT_SID"
   ```
3. Copy your **Auth Token** and set it as an environment variable using the following command. Replace *YOUR\_AUTH\_TOKEN* with your actual Auth Token.
   ```bash
   $Env:TWILIO_AUTH_TOKEN="YOUR_AUTH_TOKEN"
   ```

## Make an outgoing phone call

Follow these steps to make a phone call from your Twilio number.

## Python

1. Create a file named `make_call.py` and add the following code:

   Make a phone call using Twilio
   ```python
   # Download the helper library from https://www.twilio.com/docs/python/install
   import os
   from twilio.rest import Client

   # Find your Account SID and Auth Token at twilio.com/console
   # and set the environment variables. See http://twil.io/secure
   account_sid = os.environ["TWILIO_ACCOUNT_SID"]
   auth_token = os.environ["TWILIO_AUTH_TOKEN"]
   client = Client(account_sid, auth_token)

   call = client.calls.create(
       url="http://demo.twilio.com/docs/voice.xml",
       to="+18005550100",
       from_="+18005550199",
   )

   print(call.sid)
   ```
2. Replace the `from_` phone number with your Twilio number.
3. Replace the `to` phone number with your own phone number.
4. Save your changes.
5. Run the script:
   ```bash
   python make_call.py
   ```
   Your phone rings and you hear the short message in the [TwiML](/docs/glossary/what-is-twilio-markup-language-twiml) document that your script links to.

## Node.js

1. Create a file named `make_call.js` in the folder where you installed Express and the Twilio SDK.
2. Add the following code to `make_call.js`:

   Make an outbound call
   ```js
   // Download the helper library from https://www.twilio.com/docs/node/install
   const twilio = require("twilio"); // Or, for ESM: import twilio from "twilio";

   // Find your Account SID and Auth Token at twilio.com/console
   // and set the environment variables. See http://twil.io/secure
   const accountSid = process.env.TWILIO_ACCOUNT_SID;
   const authToken = process.env.TWILIO_AUTH_TOKEN;
   const client = twilio(accountSid, authToken);

   async function createCall() {
     const call = await client.calls.create({
       from: "+18005550199",
       to: "+18005550100",
       url: "http://demo.twilio.com/docs/voice.xml",
     });

     console.log(call.sid);
   }

   createCall();
   ```
3. Replace the `from` phone number with your Twilio number.
4. Replace the `to` phone number with your own phone number.
5. Save your changes.
6. Run the script:
   ```bash
   node make_call.js
   ```
   Your phone rings and you hear the short message in the [TwiML](/docs/glossary/what-is-twilio-markup-language-twiml) document that your script links to.

## PHP

1. Create a file named `make_call.php` in the folder where you installed the Twilio SDK.
2. Add the following code to `make_call.php`:

   Make a phone call using Twilio
   ```php
   <?php

   // Update the path below to your autoload.php,
   // see https://getcomposer.org/doc/01-basic-usage.md
   require_once "/path/to/vendor/autoload.php";

   use Twilio\Rest\Client;

   // Find your Account SID and Auth Token at twilio.com/console
   // and set the environment variables. See http://twil.io/secure
   $sid = getenv("TWILIO_ACCOUNT_SID");
   $token = getenv("TWILIO_AUTH_TOKEN");
   $twilio = new Client($sid, $token);

   $call = $twilio->calls->create(
       "+18005550100", // To
       "+18005550199", // From
       ["url" => "http://demo.twilio.com/docs/voice.xml"]
   );

   print $call->sid;
   ```
3. Update line 5 of `make_call.php` to `require __DIR__ . '/vendor/autoload.php';`
4. Replace the first argument to `$twilio->messages->create()` with your own phone number.
5. Replace the second argument to `$twilio->messages->create()` with your Twilio phone number.
6. Save your changes.
7. Run the script:
   ```bash
   php make_call.php
   ```
   Your phone rings and you hear the short message in the [TwiML](/docs/glossary/what-is-twilio-markup-language-twiml) document that your script links to.

## C#/.NET

1. Create a directory for this project:
   ```bash
   mkdir voice-quickstart
   ```
2. Open that directory in the terminal:
   ```bash
   cd voice-quickstart
   ```
3. Initialize your app:
   ```bash
   dotnet new web
   ```
4. Install the Twilio .NET SDK:
   ```bash
   dotnet add package Twilio
   ```
5. Replace the contents of `Program.cs` with the following code:

   Make a phone call using Twilio
   ```csharp
   // Install the C# / .NET helper library from twilio.com/docs/csharp/install

   using System;
   using Twilio;
   using Twilio.Rest.Api.V2010.Account;
   using System.Threading.Tasks;

   class Program {
       public static async Task Main(string[] args) {
           // Find your Account SID and Auth Token at twilio.com/console
           // and set the environment variables. See http://twil.io/secure
           string accountSid = Environment.GetEnvironmentVariable("TWILIO_ACCOUNT_SID");
           string authToken = Environment.GetEnvironmentVariable("TWILIO_AUTH_TOKEN");

           TwilioClient.Init(accountSid, authToken);

           var call = await CallResource.CreateAsync(
               url: new Uri("http://demo.twilio.com/docs/voice.xml"),
               to: new Twilio.Types.PhoneNumber("+18005550100"),
               from: new Twilio.Types.PhoneNumber("+18005550199"));

           Console.WriteLine(call.Sid);
       }
   }
   ```
6. Replace the `from` phone number with your Twilio number.
7. Replace the `to` phone number with your own phone number.
8. Save your changes.
9. Run the app:
   ```bash
   dotnet run
   ```
   Your phone rings and you hear the short message in the [TwiML](/docs/glossary/what-is-twilio-markup-language-twiml) document that your script links to.

## Java

1. Create a folder for this project:
   ```bash
   mkdir voice-quickstart
   ```
2. Go to the project folder:
   ```bash
   cd voice-quickstart
   ```
3. Initialize the app:
   ```bash
   gradle init --type basic --dsl groovy --use-defaults
   ```
4. Create folders for the project code:
   ```bash
   mkdir -p src/main/java
   ```
5. Replace the contents of the `build.gradle` file with the following code:
   ```java
   plugins {
       id 'java'
       id 'application'
   }

   application {
       mainClass = 'Example'
   }

   repositories {
       mavenCentral()
   }

   dependencies {
       implementation 'com.twilio.sdk:twilio:10.5.2'
       implementation 'org.slf4j:slf4j-simple:2.0.16'
       implementation 'com.sparkjava:spark-core:2.9.4'
   }
   ```
6. Save the file.
7. Create a file named `Example.java` in `src/main/java` and add the following code:

   Make a phone call using Twilio
   ```java
   // Install the Java helper library from twilio.com/docs/java/install

   import java.net.URI;
   import com.twilio.Twilio;
   import com.twilio.rest.api.v2010.account.Call;

   public class Example {
       // Find your Account SID and Auth Token at twilio.com/console
       // and set the environment variables. See http://twil.io/secure
       public static final String ACCOUNT_SID = System.getenv("TWILIO_ACCOUNT_SID");
       public static final String AUTH_TOKEN = System.getenv("TWILIO_AUTH_TOKEN");

       public static void main(String[] args) {
           Twilio.init(ACCOUNT_SID, AUTH_TOKEN);
           Call call = Call.creator(new com.twilio.type.PhoneNumber("+18005550100"),
                               new com.twilio.type.PhoneNumber("+18005550199"),
                               URI.create("http://demo.twilio.com/docs/voice.xml"))
                           .create();

           System.out.println(call.getSid());
       }
   }
   ```
8. Replace `+18005550199` with your Twilio phone number.
9. Replace `+18005550100` with your own phone number.
10. Save your changes.
11. Run the app:
    ```bash
    gradle run
    ```
    Your phone rings and you hear the short message in the [TwiML](/docs/glossary/what-is-twilio-markup-language-twiml) document that your script links to.

## Go

1. Create a folder for this project:
   ```bash
   mkdir voice-quickstart
   ```
2. Go to the folder:
   ```bash
   cd voice-quickstart
   ```
3. Create a Go module:
   ```bash
   go mod init voice-quickstart
   ```
4. Create a file named `make_call.go` and add the following code:

   Make a phone call using Twilio
   ```go
   // Download the helper library from https://www.twilio.com/docs/go/install
   package main

   import (
   	"fmt"
   	"github.com/twilio/twilio-go"
   	api "github.com/twilio/twilio-go/rest/api/v2010"
   	"os"
   )

   func main() {
   	// Find your Account SID and Auth Token at twilio.com/console
   	// and set the environment variables. See http://twil.io/secure
   	// Make sure TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN exists in your environment
   	client := twilio.NewRestClient()

   	params := &api.CreateCallParams{}
   	params.SetUrl("http://demo.twilio.com/docs/voice.xml")
   	params.SetTo("+18005550100")
   	params.SetFrom("+18005550199")

   	resp, err := client.Api.CreateCall(params)
   	if err != nil {
   		fmt.Println(err.Error())
   		os.Exit(1)
   	} else {
   		if resp.Sid != nil {
   			fmt.Println(*resp.Sid)
   		} else {
   			fmt.Println(resp.Sid)
   		}
   	}
   }
   ```
5. Replace the `from` phone number with your Twilio number.
6. Replace the `to` phone number with your own phone number.
7. Save your changes.
8. Install dependencies:
   ```bash
   go get
   ```
9. Run the script:
   ```bash
   go run make_call.go
   ```
   Your phone rings and you hear the short message in the [TwiML](/docs/glossary/what-is-twilio-markup-language-twiml) document that your script links to.

## Ruby

1. Create a Gemfile:
   ```bash
   bundle init
   ```
2. Install [Sinatra](https://sinatrarb.com/) and other project dependencies:
   ```bash
   bundle add puma twilio-ruby sinatra
   ```
3. Create a file named `make_call.rb` and add the following code:

   Make a phone call using Twilio
   ```ruby
   # Download the helper library from https://www.twilio.com/docs/ruby/install
   require 'twilio-ruby'

   # Find your Account SID and Auth Token at twilio.com/console
   # and set the environment variables. See http://twil.io/secure
   account_sid = ENV['TWILIO_ACCOUNT_SID']
   auth_token = ENV['TWILIO_AUTH_TOKEN']
   @client = Twilio::REST::Client.new(account_sid, auth_token)

   call = @client
          .api
          .v2010
          .calls
          .create(
            url: 'http://demo.twilio.com/docs/voice.xml',
            to: '+18005550100',
            from: '+18005550199'
          )

   puts call.sid
   ```
4. Replace the `from` phone number with your Twilio number.
5. Replace the `to` phone number with your own phone number.
6. Save your changes.
7. Run the script:
   ```bash
   ruby make_call.rb
   ```
   Your phone rings and you hear the short message in the [TwiML](/docs/glossary/what-is-twilio-markup-language-twiml) document that your script links to.

## Receive a phone call with your Twilio number

Follow these steps to receive a phone call with your Twilio number and respond using text-to-speech.

## Python

1. Create a file named `answer_phone.py` and add the following code:

   Generate TwiML to Say a message
   ```py
   from flask import Flask
   from twilio.twiml.voice_response import VoiceResponse

   app = Flask(__name__)


   @app.route("/", methods=['GET', 'POST'])
   def hello_monkey():
       """Respond to incoming calls with a simple text message."""

       resp = VoiceResponse()
       resp.say("Hello from your pals at Twilio! Have fun.")
       return str(resp)


   if __name__ == "__main__":
       app.run(debug=True)
   ```
2. Save the file.
3. In a new terminal window, run the following command to start the Python development server:

   ```bash
   python answer_phone.py 
   ```
4. In a new terminal window, run the following command to start [ngrok](https://ngrok.com/docs/what-is-ngrok/) and create a tunnel to your localhost:

   ```bash
   ngrok http 5000
   ```
5. Set up a webhook that triggers when your Twilio phone number receives a phone call:
   1. Go to the [Active Numbers](https://www.twilio.com/console/phone-numbers/incoming) page in the Twilio Console.
   2. Click your Twilio phone number.
   3. Go to the **Configure** tab and find the **Voice Configuration** section.
   4. In the **A call comes in** row, select the **Webhook** option.
   5. Paste your ngrok public URL in the **URL** field. For example, if your ngrok console shows `Forwarding https://1aaa-123-45-678-910.ngrok-free.app`, enter `https://1aaa-123-45-678-910.ngrok-free.app`.
   6. Click **Save configuration**.
6. With the Python development server and ngrok running, call your Twilio phone number. You hear the text-to-speech message defined in `answer_phone.py`.

## Node.js

1. Create a file named `answer_phone.js` in the same folder as `make_call.js` and add the following code:

   Generate TwiML to Say a message
   ```js
   const express = require('express');
   const VoiceResponse = require('twilio').twiml.VoiceResponse;

   const app = express();

   // Create a route that will handle Twilio webhook requests, sent as an
   // HTTP POST to /voice in our application
   app.post('/voice', (request, response) => {
     // Use the Twilio Node.js SDK to build an XML response
       const twiml = new VoiceResponse();

       twiml.say('Hello from your pals at Twilio! Have fun.');

     // Render the response as XML in reply to the webhook request
     response.type('text/xml');
     response.send(twiml.toString());
   });

   // Create an HTTP server and listen for requests on port 1337
   app.listen(1337, () => {
       console.log('TwiML server running at http://127.0.0.1:1337/');
   });
   ```
2. Save the file.
3. In a new terminal window, run the following command to start your server:
   ```bash
   node answer_phone.js
   ```
4. In a new terminal window, run the following command to start [ngrok](https://ngrok.com/docs/what-is-ngrok/) and create a tunnel to your localhost:
   ```bash
   ngrok http 1337
   ```
5. Set up a webhook that triggers when your Twilio phone number receives a phone call:
   1. Go to the [Active Numbers](https://www.twilio.com/console/phone-numbers/incoming) page in the Twilio Console.
   2. Click your Twilio phone number.
   3. Go to the **Configure** tab and find the **Voice Configuration** section.
   4. In the **A call comes in** row, select the **Webhook** option.
   5. Append `/voice` to your ngrok public URL, and then paste the result into the **URL** field. For example, if your ngrok console shows `Forwarding https://1aaa-123-45-678-910.ngrok-free.app`, enter `https://1aaa-123-45-678-910.ngrok-free.app/voice`.
   6. Click **Save configuration**.
6. With your server and ngrok running, call your Twilio phone number. You hear the text-to-speech message defined in `answer_phone.js`.

## PHP

1. Create a file named `answer_call.php` in the same folder as `make_call.php` and add the following code:
   ```php
   <?php
   require __DIR__ . '/vendor/autoload.php';
   use Twilio\TwiML\VoiceResponse;

   // Start our TwiML response
   $response = new VoiceResponse();

   // Read a message aloud to the caller
   $response->say(
       "Thank you for calling! Have a great day.",
       ["voice" => "Polly.Amy"]
   );

   echo $response;
   ```
2. Save the file.
3. In a new terminal window, run the following command to start your PHP development server:
   ```bash
   php -S localhost:8000 answer_call.php
   ```
4. In a new terminal window, run the following command to start [ngrok](https://ngrok.com/docs/what-is-ngrok/) and create a tunnel to your localhost:
   ```bash
   ngrok http 8000
   ```
5. Set up a webhook that triggers when your Twilio phone number receives a phone call:
   1. Go to the [Active Numbers](https://www.twilio.com/console/phone-numbers/incoming) page in the Twilio Console.
   2. Click your Twilio phone number.
   3. Go to the **Configure** tab and find the **Voice Configuration** section.
   4. In the **A call comes in** row, select the **Webhook** option.
   5. Paste your ngrok public URL in the **URL** field (for example, `https://ff4660c91380.ngrok.app`).
   6. Click **Save configuration**.
6. With the PHP development server and ngrok running, call your Twilio phone number. You hear the text-to-speech message defined in `answer_call.php`.

## C#/.NET

1. Replace the contents of `Program.cs` with the following code:

```cs
using Twilio.TwiML;
var builder = WebApplication.CreateBuilder(args);
var app = builder.Build();

app.MapMethods("/", ["GET", "POST"], () =>
{
 var response = new VoiceResponse()
     .Say("Thank you for calling! Have a great day.");
 return Results.Text(response.ToString(), "application/xml");
});

app.Run("http://localhost:4567");
```

2. Save the file.
3. In a new terminal window, run the following command to start your development server:
   ```bash
   dotnet run
   ```
4. In a new terminal window, run the following command to start [ngrok](https://ngrok.com/docs/what-is-ngrok/) and create a tunnel to your localhost:
   ```bash
   ngrok http 4567
   ```
5. Set up a webhook that triggers when your Twilio phone number receives a phone call:
   1. Go to the [Active Numbers](https://www.twilio.com/console/phone-numbers/incoming) page in the Twilio Console.
   2. Click your Twilio phone number.
   3. Go to the **Configure** tab and find the **Voice Configuration** section.
   4. In the **A call comes in** row, select the **Webhook** option.
   5. Paste your ngrok public URL in the **URL** field (for example, `https://ff4660c91380.ngrok.app`).
   6. Click **Save configuration**.
6. With your development server and ngrok running, call your Twilio phone number. You hear the text-to-speech message defined in `Program.cs`.

## Java

1. Create a file named `VoiceApp.java` in the `src/main/java` directory and add the following code:

   Generate TwiML to Say a message
   ```java
   import com.twilio.twiml.VoiceResponse;
   import com.twilio.twiml.voice.Say;

   import static spark.Spark.*;

   public class VoiceApp {
       public static void main(String[] args) {

           get("/hello", (req, res) -> "Hello Web");

           post("/", (request, response) -> {
               Say say  = new Say.Builder(
                       "Hello from your pals at Twilio! Have fun.")
                       .build();
               VoiceResponse voiceResponse = new VoiceResponse.Builder()
                       .say(say)
                       .build();
               return voiceResponse.toXml();
           });
       }
   }
   ```
2. Save the file.
3. Open the `build.gradle` file and replace `Example` with `VoiceApp`. Save the file.
4. In a new terminal window, run the following command to start your Spark server:
   ```bash
   gradle run
   ```
5. In a new terminal window, run the following command to start [ngrok](https://ngrok.com/docs/what-is-ngrok/) and create a tunnel to your localhost:
   ```bash
   ngrok http 4567
   ```
6. Set up a webhook that triggers when your Twilio phone number receives a phone call:
   1. Go to the [Active Numbers](https://www.twilio.com/console/phone-numbers/incoming) page in the Twilio Console.
   2. Click your Twilio phone number.
   3. Go to the **Configure** tab and find the **Voice Configuration** section.
   4. In the **A call comes in** row, select the **Webhook** option.
   5. Paste your ngrok public URL in the **URL** field (for example, `https://ff4660c91380.ngrok.app`).
   6. Click **Save configuration**.
7. With your Spark server and ngrok running, call your Twilio phone number. You hear the text-to-speech message defined in `VoiceApp.java`.

## Go

1. Create a file named `main.go` and add the following code:

   Generate TwiML to Say a message
   ```go
   package main

   import (
   	"net/http"

   	"github.com/gin-gonic/gin"
   	"github.com/twilio/twilio-go/twiml"
   )

   func main() {
   	router := gin.Default()

   	router.POST("/answer", func(context *gin.Context) {
   		say := &twiml.VoiceSay{
   			Message: "Hello from your pals at Twilio! Have fun.",
   		}

   		twimlResult, err := twiml.Voice([]twiml.Element{say})
   		if err != nil {
   			context.String(http.StatusInternalServerError, err.Error())
   		} else {
   			context.Header("Content-Type", "text/xml")
   			context.String(http.StatusOK, twimlResult)
   		}
   	})

   	router.Run(":1337")
   }
   ```
2. Save the file.
3. Install [Gin](https://gin-gonic.com/) and other dependencies:
   ```bash
   go get
   ```
4. In a new terminal window, run the following command to start your Gin app:
   ```bash
   go run main.go
   ```
5. In a new terminal window, run the following command to start [ngrok](https://ngrok.com/docs/what-is-ngrok/) and create a tunnel to your localhost:
   ```bash
   ngrok http 1337
   ```
6. Set up a webhook that triggers when your Twilio phone number receives a phone call:
   1. Go to the [Active Numbers](https://www.twilio.com/console/phone-numbers/incoming) page in the Twilio Console.
   2. Click your Twilio phone number.
   3. Go to the **Configure** tab and find the **Voice Configuration** section.
   4. In the **A call comes in** row, select the **Webhook** option.
   5. Paste your ngrok public URL in the **URL** field with `/answer` appended (for example, `https://ff4660c91380.ngrok.app/answer`).
   6. Click **Save configuration**.
7. With your Gin app and ngrok running, call your Twilio phone number. You hear the text-to-speech message defined in `main.go`.

## Ruby

1. Create a file named `answer_call.rb` in the same folder as `make_call.rb` and add the following code:
   ```rb
   require 'sinatra'
   require 'twilio-ruby'

   configure :development do
     set :host_authorization, { permitted_hosts: [] }
   end

   def self.get_or_post(url,&block)
     get(url,&block)
     post(url,&block)
   end

   get_or_post '/' do
     content_type 'text/xml'

     Twilio::TwiML::VoiceResponse.new do | response |
       response.say(message: "Ahoy world!")
     end.to_s
   end
   ```
2. Save the file.
3. In a new terminal window, run the following command to start your Sinatra server:
   ```bash
   ruby answer_call.rb
   ```
4. In a new terminal window, run the following command to start [ngrok](https://ngrok.com/docs/what-is-ngrok/) and create a tunnel to your localhost:
   ```bash
   ngrok http 4567
   ```
5. Set up a webhook that triggers when your Twilio phone number receives a phone call:
   1. Go to the [Active Numbers](https://www.twilio.com/console/phone-numbers/incoming) page in the Twilio Console.
   2. Click your Twilio phone number.
   3. Go to the **Configure** tab and find the **Voice Configuration** section.
   4. In the **A call comes in** row, select the **Webhook** option.
   5. Paste your ngrok public URL in the **URL** field (for example, `https://ff4660c91380.ngrok.app`).
   6. Click **Save configuration**.
6. With your Sinatra server and ngrok running, call your Twilio phone number. You hear the text-to-speech message defined in `answer_call.rb`.

## Next steps

* Browse [reference documentation for the Programmable Voice API](/docs/voice/api)
* Learn about [TwiML markup language](/docs/voice/twiml) for responding to voice calls
* Browse all [voice tutorials](/docs/voice/tutorials) by topic
