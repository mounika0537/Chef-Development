import json
import os
from Questionaire import questionAndAnswersData 
# from textractor import Textractor
# from textractor.data.constants import TextractFeatures
# from textractor.parsers import response_parser
from textractor.entities.document import Document
import boto3
import botocore
from LoadConfiguration import GetConfigurationData
import ast
import logging
from DBConnector import DBConnector
from datetime import datetime
import SendQueueItem as queueItem
import re
import difflib
from dateutil import parser
import CheckBoxSelectionHelper
from datetime import datetime
from pytz import timezone


logging.basicConfig()
logger = logging.getLogger()
logging.getLogger("botocore").setLevel(logging.ERROR)
logger.setLevel(logging.INFO)
sqsClient = boto3.client('sqs', region_name='us-east-1')
secret_name = "dpa/hra/db"
region_name = "us-east-1"
# Create a Secrets Manager client
session = boto3.session.Session()
client = session.client(service_name='secretsmanager', region_name=region_name)
ssm_client = boto3.client('ssm')

def lambda_handler(event, context):
    try:
        # print(event)
        # print(f"receiptHandle is: {event['Records'][0]['receiptHandle']}")
        # jsonbodyResp = ast.literal_eval(event['Records'][0]['body'])
        # print(f"Messsage Received: {jsonbodyResp}")
        # jsonMessage = ast.literal_eval(jsonbodyResp['Message']) 
        # print(f"start_document_analysis Job ID: {jsonMessage['JobId']}")
        # logger.info("start_document_analysis Job ID:" + jsonMessage['JobId'])
        # print(f"Job for processing: {jsonMessage['DocumentLocation']['S3ObjectName']}")
        # bucket = jsonMessage['DocumentLocation']['S3Bucket']
        # print('Bucket Name: ' + bucket)
        # s3Key = jsonMessage['DocumentLocation']['S3ObjectName']
        # print(f"S3Key: {s3Key}")
        
        # job_Id = '4cc5776f7299e5e4b1cc5b757aac874488da6a9f535a36fdb16e2c46a8f33c98'          
        bucket = 'dpa-hra-textract-extraction'
        #s3Key = 'hra.tif'
        #s3Key = 'L4017134_25066L494.tif'
        s3Key = 'dsnp.tif'
    
        # os.environ['REQUESTS_CA_BUNDLE'] = '/etc/ssl/certs/ca-certificates.crt'
        # os.environ['AWS_CA_BUNDLE'] = '/etc/ssl/certs/ca-certificates.crt'
        sqsParameterKey='/dpa/hra/sqsUrl'
        sqsURL = ssm_client.get_parameter(Name=sqsParameterKey, WithDecryption=True)
    
        s3ouptputParameterKey='/dpa/hra/s3outputbucket'
        s3OutputBucket = ssm_client.get_parameter(Name=s3ouptputParameterKey, WithDecryption=True)

        s3 = boto3.client('s3')
        fileName = 'textractresponse/' + s3Key.replace('pdf', 'json').replace('tif', 'json')
        document= None
        try:
            content = s3.head_object(Bucket=s3OutputBucket['Parameter']['Value'],Key=fileName)
            if content.get('ResponseMetadata',None) is not None:
                print("File exists - s3://%s/%s " %(s3OutputBucket['Parameter']['Value'],fileName))
        except botocore.exceptions.ClientError as error:
            print("File does not exist - s3://%s/%s " %(s3OutputBucket['Parameter']['Value'],fileName))
            awsTextract = boto3.client('textract')
            docResponse = awsTextract.get_document_analysis(JobId=jsonMessage['JobId'])
            results = docResponse.copy()
            while "NextToken" in docResponse:
                docResponse = awsTextract.get_document_analysis(JobId=jsonMessage['JobId'], NextToken=docResponse['NextToken'])        
                results['Blocks'].extend(docResponse['Blocks']) 
        
            textractResponse = json.dumps(results)
            s3.put_object(Body=textractResponse, Bucket=s3OutputBucket['Parameter']['Value'], Key=fileName)
    
        getSecretValueResponse = client.get_secret_value(SecretId=secret_name)
        jsonSecret = json.loads(getSecretValueResponse['SecretString'])

        db = DBConnector(jsonSecret['Server'], jsonSecret['Database'], jsonSecret['UserName'], jsonSecret['Pwd'])
        db.UpdateTransactionStatus(s3Key, 'Extraction', 'Started', None, None)    
        # sqsResponse = sqsClient.delete_message(QueueUrl = sqsURL['Parameter']['Value'], ReceiptHandle=event['Records'][0]['receiptHandle']) 
        # print(f"Receipt Handle Deleted from Queue:{sqsResponse}")
            
        configData = GetConfigurationData()
        skipList = configData.GetSkipQuestions()
        trackingQuestions = configData.GetTrackingQuestions()
        ignoreList = configData.GetIgnoreQuestions()
       
        #document = Document.open('s3://' + s3OutputBucket['Parameter']['Value'] +'/' +fileName)
        document = Document.open("C:\\Users\\u110011\\Downloads\\" + s3Key.replace('pdf', 'json').replace('tif', 'json'))
        results = document.response
        
        print(f"Total Number of Pages present in the document: {results['DocumentMetadata']['Pages']}")

        respDictionary = {}
        hraDictionary = {}
        hraDictionary["What is your ethnicity?"] = ["African", "African American", "Native", "Native American", "Pacific", "Pacific Islander","Native", "Native Hawaiian", "Indian", "Indian American", "Asian", "Caucasian", "Hispanic", "Other"]
        header_index = 0
        currentProcessingQuestion=None
        answerList = []
        questionConfidence=None
        previousLine = None
        handwrittenTextFlag = False
        Handwritten_blocks = []
        currentProcessingPage = 0
        previousPage = 0

        extract_pages, skip_pages = GetExtractableAndSkippablePages(results['Blocks'], trackingQuestions)
        print("Extractable Pages: ", extract_pages)
        print("Skippable Pages: ", skip_pages)


   
        for pageBlk in filter(lambda blk: blk['BlockType'] == 'PAGE', results['Blocks']):
            for lineBlk in filter(lambda blk: blk['BlockType'] == 'LINE' and blk['Page'] == pageBlk['Page'], results['Blocks']):
                # Do something with lineBlk
                print(f"Processing Line Block: {lineBlk['Text']} on Page {pageBlk['Page']}")
                if lineBlk['Text'].strip() in [item.strip() for item in ignoreList]:
                    continue                    
                
                if lineBlk['Text'] in [x for v in hraDictionary.values() for x in v] or (currentProcessingQuestion is not None and 'What is your ethnicity' in currentProcessingQuestion and 'Other' in lineBlk['Text']):
                    answerListCount = len(answerList)
                    CheckBoxSelectionHelper.CheckCheckBoxValues(lineBlk, results, answerList, questionConfidence)
                    # if no CELL Blocks present to capture response, try second option by traversing from Line->KEY_VALUE_SET path
                    if (len(answerList) == answerListCount):
                        CheckBoxSelectionHelper.CheckCheckBoxAnswer(lineBlk, results, answerList, questionConfidence, document.checkboxes)
                    # Last option: Get Answer from Document textractor object
                    if (len(answerList) == answerListCount):     
                        CheckBoxSelectionHelper.GetCheckBoxAnswerFromDocument(document.checkboxes, lineBlk, questionConfidence, answerList) 
                    continue
            
                if lineBlk['Text'] not in skipList and lineBlk['Text'] not in ignoreList:
                    header_index = header_index+1
                    if header_index <= 3: 
                        print(f"{lineBlk['Text']}:-{lineBlk['Confidence']}")
                        AddHeaderDetails_dsnp(respDictionary, lineBlk)
                        #AddHeaderDetails(respDictionary, lineBlk)
                        continue
                if lineBlk['Text'] in skipList:
                    respDictionary[str(lineBlk['Text'])] = questionAndAnswersData(lineBlk['Confidence'], lineBlk['Text'], None, lineBlk['Confidence'], 'No', lineBlk['Page'])
                    continue
                #print(f"Header Index is {header_index} for Page {pageBlk['Page']}")
                print(f"{lineBlk['Text']}:-{lineBlk['Confidence']}")            
                lineBlk['Text'] = lineBlk['Text'].strip().replace("'","''")
                lineBlk['Text'] = lineBlk['Text'].strip().replace("\"",'')
                if "'" in lineBlk['Text']:
                    print(f"After removing single quote characters if there are any: {lineBlk['Text']}:-{lineBlk['Confidence']}")

                if currentProcessingQuestion is not None and "What is your ethnicity?" in currentProcessingQuestion and lineBlk['Text'] in ["American", "Islander", "Hawaiian"]:
                    continue
                
                #processing tracking questions
                TextInQuestionBank, formattedQuestionText = DoesTextExistsInHRAQuestionBank(lineBlk['Text'], lineBlk['Page'], trackingQuestions)
                if TextInQuestionBank:
                    lineBlk['Text'] = formattedQuestionText
                if TextInQuestionBank and currentProcessingQuestion is None:
                    currentProcessingQuestion = lineBlk['Text']
                    questionConfidence = lineBlk['Confidence']
                    continue
                elif TextInQuestionBank and currentProcessingQuestion != lineBlk['Text']:
                    if '2. Have you had a physical exam provided by your primary care physician (PCP) in the last' in currentProcessingQuestion:
                        currentProcessingQuestion = '2. Have you had a physical exam provided by your primary care physician (PCP) in the last year?'
                    elif 'If you have a caregiver(s) that assists you with any of the above activities, please provide their' in currentProcessingQuestion:
                        currentProcessingQuestion = '5. If you have a caregiver(s) that assists you with any of the above activities, please provide their names(s) below:'
                    elif 'If you have a caregiver(s) that assists you with any of the above activities, please provide' in currentProcessingQuestion:
                        currentProcessingQuestion = '5. If you have a caregiver(s) that assists you with any of the above activities, please provide their names(s) and relationship to you below:'
                
                    elif currentProcessingQuestion=='10. In the previous 6 months, have you been treated in the Emergency Room for a medical condition':
                        currentProcessingQuestion = '10. In the previous 6 months, have you been treated in the Emergency Room for a medical condition other than an accident?'
                    elif currentProcessingQuestion=='4. Have you ever thought you should cut down on your use of alcohol or use of drugs not prescribed by':
                        currentProcessingQuestion = '4. Have you ever thought you should cut down on your use of alcohol or use of drugs not prescribed by your doctor?'
                    elif currentProcessingQuestion=='4. How often do you need to have someone help you when you read instruction, pamphlets or other':
                        currentProcessingQuestion = '4. How often do you need to have someone help you when you read instruction, pamphlets or other written material from your doctor or pharmacy?'
                    elif currentProcessingQuestion=='5. Do you need help with food, clothing, utilities or housing?':
                        currentProcessingQuestion = '5. Do you need help with food, clothing, utilities or housing? (This could be trouble paying your heating bill, no working refrigerator or no permanent place to live.)'
                    elif currentProcessingQuestion=='7. How often is stress a problem for you in handling everyday things such as your health, money, work,':
                        currentProcessingQuestion = '7. How often is stress a problem for you in handling everyday things such as your health, money, work, or relationships with family and friends?'
                    elif currentProcessingQuestion==' 9. In the last 6 months, have you stayed at a hospital overnight because of a medical':
                        currentProcessingQuestion = '9. In the last 6 months, have you stayed at a hospital overnight because of a medical condition?'
                    elif currentProcessingQuestion=='10. In the previous 6 months, have you been treated in the Emergency Room for a medical':
                        currentProcessingQuestion = '10. In the previous 6 months, have you been treated in the Emergency Room for a medical condition other than an accident?'
                    elif currentProcessingQuestion=='Do you currently meet with a mental health provider like a councelor, psychiatrist, or':
                        currentProcessingQuestion = 'Do you currently meet with a mental health provider like a counselor, psychiatrist, or therapist?'
                    elif currentProcessingQuestion=='Has lack of transportation prevented you from getting to a medical appointments or retrieving':
                        currentProcessingQuestion = 'Has lack of transportation prevented you from getting to a medical appointments or retrieving necessary medications?'
                    elif currentProcessingQuestion=='Has lack of transportation prevented you from getting to non-medical meetings,':
                        currentProcessingQuestion = 'Has lack of transportation prevented you from getting to non-medical meetings, appointments, work, or retriving things needed for daily living?'
                    elif currentProcessingQuestion=='How often do you need someone to help you read instructions, pamphlets or other written':
                        currentProcessingQuestion = 'How often do you need someone to help you read instructions, pamphlets or other written material from your doctor or pharmacy?'

                    
                    
                    if "medical conditions do you have" in currentProcessingQuestion and "have you had in the past" in currentProcessingQuestion:
                        if len(answerList) > 0 and "Cancer" in answerList[len(answerList)-1].answerText and "type" in answerList[len(answerList)-1].answerText:               
                            typePostion = answerList[len(answerList)-1].answerText.index('type')
                            hwText = answerList[len(answerList)-1].answerText[typePostion+4:]
                            hwText = hwText.replace(':','')
                            if len(hwText.strip()) > 0:
                                answerList[len(answerList)-1].answerText = "Cancer; If yes, what type:"
                                answerList[len(answerList)-1].HandWrittenText = hwText
                                answerList[len(answerList)-1].IsHandWritten = "Yes"
                                answerList[len(answerList)-1].answerSelection = "SELECTED"
                            if len(answerList) < 20:
                                ReValidateMedicalConditions(answerList, document, questionConfidence)
                        if len(answerList) > 0 and "Cancer" in answerList[4].answerText and "have" in answerList[4].answerText:
                            havePosition = answerList[4].answerText.index('have')
                            hwText = answerList[4].answerText[havePosition+4:]
                            hwText = hwText.replace(':','')
                            if len(hwText.strip()) > 0:
                                answerList[4].answerText = "Cancer; If yes, what type:"
                                answerList[4].HandWrittenText = hwText
                                answerList[4].IsHandWritten = "Yes"
                                answerList[4].answerSelection = "SELECTED"
                        if len(answerList) > 0 and "Diabetes" in answerList[10].answerText and "level" in answerList[10].answerText:
                            levelPosition = answerList[10].answerText.index('level')
                            hwText = answerList[10].answerText[levelPosition+5:]
                            hwText = hwText.replace('?','')
                            if len(hwText.strip()) > 0:
                                answerList[10].answerText = "Diabetes; If yes, what was your last A1C level:"
                                answerList[10].HandWrittenText = hwText
                                answerList[10].IsHandWritten = "Yes"
                                answerList[10].answerSelection = "SELECTED"
                            if len(answerList) < 26:
                                ReValidateMedicalConditions(answerList, document, questionConfidence)
                            
                        

                
                    
                    
                    respDictionary[currentProcessingQuestion] = answerList
                    answerList=[]
                    questionConfidence=None
                    currentProcessingQuestion = lineBlk['Text']
                    questionConfidence = lineBlk['Confidence']
                    continue

                if currentProcessingQuestion == "If yes, diet type? (For example, you could be on a low fiber, salt-restricted, or" \
                    and 'mechanical soft diet.)' in lineBlk['Text']:
                    lineBlk['Text'] = lineBlk['Text'].replace('mechanical soft diet.)', '')
                    currentProcessingQuestion = "If yes, diet type? (For example, you could be on a low fiber, salt-restricted, or mechanical soft diet)"
                    answerList.append(questionAndAnswersData(questionConfidence, lineBlk['Text'].strip(), None, lineBlk['Confidence'], 'Yes', lineBlk['Page'], lineBlk['Text'].strip()))
                    respDictionary[currentProcessingQuestion] = answerList
                    answerList=[]
                    questionConfidence=None
                    currentProcessingQuestion = None
                    questionConfidence = None
                    continue


                if currentProcessingQuestion == '3. What is your current height?' or currentProcessingQuestion == '4. What is your current weight?' or currentProcessingQuestion == '4. What is your current weight in pounds (lbs)?':  
                    FormatHeightAndWeigtAnswers(lineBlk, answerList, questionConfidence, currentProcessingQuestion, results)             
                    continue

                if currentProcessingQuestion == '5. If you have a caregiver(s) that assists you with any of the above activities, please provide their' \
                    and 'name(s) below' in lineBlk['Text']:
                    lineBlk['Text'] = lineBlk['Text'].replace('name(s) below:', '')
                    lineBlk['Text'] = lineBlk['Text'].replace('name(s) below', '')
                    currentProcessingQuestion = '5. If you have a caregiver(s) that assists you with any of the above activities, please provide their names(s) below:'
                    answerList.append(questionAndAnswersData(questionConfidence, lineBlk['Text'].strip(), None, lineBlk['Confidence'], 'Yes', lineBlk['Page'], lineBlk['Text'].strip()))
                    respDictionary[currentProcessingQuestion] = answerList
                    answerList=[]
                    questionConfidence=None
                    currentProcessingQuestion = None
                    questionConfidence = None
                    continue  

                if "Caregiver Name:" in currentProcessingQuestion:
                    wordBlks= filter(lambda wblk: (wblk['BlockType'] == 'WORD' and wblk['Text'] in lineBlk['Text'] and wblk['Id'] == lineBlk['Relationships'][0]['Ids'][0]), results['Blocks']) 
                    IsHandWritten = 'No'
                    for wordBlk in wordBlks:
                        if(wordBlk['TextType'] == 'HANDWRITING'):
                            IsHandWritten = 'Yes'                                           
                            break
                    answer = questionAndAnswersData(questionConfidence, lineBlk['Text'].replace("'", "''"), None, lineBlk['Confidence'], IsHandWritten, lineBlk['Page'], lineBlk['Text'].replace("'", "''"))
                    answerList.append(answer)
                
                if "Caregiver Relationship to you:" in currentProcessingQuestion:
                    wordBlks= filter(lambda wblk: (wblk['BlockType'] == 'WORD' and wblk['Text'] in lineBlk['Text'] and wblk['Id'] == lineBlk['Relationships'][0]['Ids'][0]), results['Blocks']) 
                    IsHandWritten = 'No'
                    for wordBlk in wordBlks:
                        if(wordBlk['TextType'] == 'HANDWRITING'):
                            IsHandWritten = 'Yes'                                           
                            break
                    answer = questionAndAnswersData(questionConfidence, lineBlk['Text'].replace("'", "''"), None, lineBlk['Confidence'], IsHandWritten, lineBlk['Page'], lineBlk['Text'].replace("'", "''"))
                    answerList.append(answer)

                

                '''if currentProcessingQuestion == '5. If you have a caregiver(s) that assists you with any of the above activities, please provide':
                    FormatCaregiverAnswers(lineBlk, answerList, questionConfidence, currentProcessingQuestion, results)             
                    continue
                
                if "Caregiver Name:" in currentProcessingQuestion:
                    lineBlk['Text'] = lineBlk['Text'].replace('Caregiver Name:', '')
                    lineBlk['Text'] = lineBlk['Text'].replace('Caregiver Name', '')
                    answerList.append(questionAndAnswersData(questionConfidence, lineBlk['Text'].strip(), None, lineBlk['Confidence'], 'Yes', lineBlk['Page'], lineBlk['Text'].strip()))
                    respDictionary[currentProcessingQuestion] = answerList
                    answerList=[]
                    questionConfidence=None
                    currentProcessingQuestion = None
                    questionConfidence = None
                    continue
                if "Caregiver Relationship to you:" in currentProcessingQuestion:
                    lineBlk['Text'] = lineBlk['Text'].replace('Caregiver Relationship to you:', '')
                    lineBlk['Text'] = lineBlk['Text'].replace('Caregiver Relationship to you', '')
                    answerList.append(questionAndAnswersData(questionConfidence, lineBlk['Text'].strip(), None, lineBlk['Confidence'], 'Yes', lineBlk['Page'], lineBlk['Text'].strip()))
                    respDictionary[currentProcessingQuestion] = answerList
                    answerList=[]
                    questionConfidence=None
                    currentProcessingQuestion = None
                    questionConfidence = None
                    continue
                '''


                ''' BELOW IS FOR PAGE NUMBERS '''
                if TextInQuestionBank is False and currentProcessingQuestion != lineBlk['Text'] and lineBlk['Text'] in ['1','2','3','4','5','6','7','8','9','10']:
                    respDictionary[currentProcessingQuestion] = answerList
                    answerList=[]
                    questionConfidence=None
                    currentProcessingQuestion = "Page Number - " + lineBlk['Text']
                    answerList.append(questionAndAnswersData(100, lineBlk['Text'].strip(), None, lineBlk['Confidence'], 'No', lineBlk['Page'], None))
                    respDictionary[currentProcessingQuestion] = answerList
                    continue
            
                if TextInQuestionBank and currentProcessingQuestion is not None:
                    currentProcessingQuestion = lineBlk['Text']
                    questionConfidence = lineBlk['Confidence']
                    continue
                if TextInQuestionBank is False and currentProcessingQuestion is not None:
                    CheckBoxSelectionHelper.CheckCheckBoxAnswer(lineBlk, results, answerList, questionConfidence, document.checkboxes)
                    #GetCheckBoxStatus(lineBlk['Text'], lineBlk['Page'], lineBlk['Relationships'][0]['Ids'][0], answerList, questionConfidence, document.checkboxes)
                    #previousLine = lineBlk['Text']    
                    continue
            

                pattern = r'^\d\s+\d+'
                match = re.search(pattern, lineBlk['Text'].strip())
                if match:
                    restructedText = re.sub(r'\s+', ' ', lineBlk['Text'].strip())
                    lineBlk['Text'] = restructedText.strip().replace(" ", "-")

                # replace lines of multi line options
                if "lung disorder" in lineBlk['Text'] and "asthma" in lineBlk['Text']:
                    lineBlk['Text'] = "Lung disorder (e.g., asthma, emphysema, chronic obstructuive pulmonary disease (COPD))"

                CheckBoxSelectionHelper.CheckCheckBoxAnswer(lineBlk, results, answerList, questionConfidence, document.checkboxes)
                #GetCheckBoxStatus(lineBlk['Text'], lineBlk['Page'], lineBlk['Relationships'][0]['Ids'][0], answerList, questionConfidence, document.checkboxes)
                previousLine = lineBlk['Text']    
                # End of Line
            #End of page
            header_index = 0
            


        for lineBlk in filter(lambda blk: (blk['BlockType'] == 'LINE'), results['Blocks']):
            currentProcessingPage = lineBlk['Page']
            if lineBlk['Page'] in extract_pages and lineBlk['Text'] not in skipList:
                print(f"Processing Page {lineBlk['Text']} for HRA Extraction")
                if previousPage != currentProcessingPage:
                    header_index = header_index+1
                    if header_index <= 3: 
                        print(f"{lineBlk['Text']}:-{lineBlk['Confidence']}")
                        AddHeaderDetails_dsnp(respDictionary, lineBlk)
                        #AddHeaderDetails(respDictionary, lineBlk)
                        continue
                    if header_index >3:
                        print(f"Header Index is {header_index} and it is greater than 3, so skipping header details")
                        header_index = 0
                        previousPage = currentProcessingPage
                print(f"Processing Line Block: {lineBlk['Text']} on Page {lineBlk['Page']}")




                if previousPage != currentProcessingPage:
                    print(f"Page changed from {previousPage} to {currentProcessingPage}")
                    header_index = 0
            elif lineBlk['Text'] in skipList:
                print(f"Text : {lineBlk['Text']} present in Skip List")
            elif lineBlk['Page'] in skip_pages:
                print(f"Skipping Page {lineBlk['Page']} as it is not extractable")
                continue

    except Exception as ex:
        print('Extraction Error:', ex)
        db.UpdateTransactionError(s3Key, 'Extraction', 'Exception', 'System Exception', ex)   

    







def GetExtractableAndSkippablePages(Blocks, trackingQuestions):
    """Organizes blocks by page and determines which pages should be extracted or skipped based on the presence of specific questions."""
    #Organize blocks by page
    pages = {}
    for block in Blocks:
        if block['BlockType'] == 'PAGE':
            page_num = block.get('Page',1)
            pages[page_num] = {
                'blocks': [],
                'extract': False
            }

    #Add Blocks to their respective pages
    for block in Blocks:
        if block['BlockType'] == 'LINE':
            page_num = block.get('Page',1)
            if page_num in pages:
                pages[page_num]['blocks'].append(block)

    #Process each page to determine if it should be extracted
    for page_num, page_data in pages.items():
        for block in page_data['blocks']:
            if block['BlockType'] == 'LINE':
                #text = block['Text'].lower().strip()
                if block['Text'] in trackingQuestions:
                    page_data['extract'] = True
                    break # No need to check other blocks if we found match
        
    #Seperate pages into 2 groups
    extract_pages = [page_num for page_num, data in pages.items() if data['extract']]
    skip_pages = [page_num for page_num, data in pages.items() if not data['extract']]

    print("extract pages : ", extract_pages)
    print("skip pages : ", skip_pages)

    return extract_pages, skip_pages

def AddHeaderDetails_dsnp(respDictionary, lineBlk):
    """Adds header details to the response dictionary based on the content of the line block."""
    text = str(lineBlk.get('Text',''))
    #Extracting identifier
    identifier_Pattern = r'(\w\d{10})|(\d{9,11})'
    id_match = re.match(identifier_Pattern, lineBlk['Text'].strip())
    if id_match:
        respDictionary['Identifier-' + str(lineBlk['Page'])] = questionAndAnswersData(lineBlk['Confidence'], lineBlk['Text'], None, lineBlk['Confidence'], 'No', lineBlk['Page'])
        return

    #Extracting Name
    name_pattern = r'[a-zA-Z]+\s[a-zA-Z]+'
    match = re.match(name_pattern, lineBlk['Text'].strip())
    if match:
        respDictionary['Name-'+ str(lineBlk['Page'])] = questionAndAnswersData(lineBlk['Confidence'], lineBlk['Text'].strip(), None, lineBlk['Confidence'], 'No', lineBlk['Page'])
        return 

    #Extracting Date
    Date_Pattern = r'\b(?:January|February|March|April|May|June|July|August|September|October|November|December) \d{1,2}, \d{4}'
    DateMatch = re.search(Date_Pattern, text)
    if DateMatch:
        extracted_date = DateMatch.group()
        print("Date: ", extracted_date)
        respDictionary['Date-' + str(lineBlk['Page'])] = questionAndAnswersData(lineBlk['Confidence'], lineBlk['Text'].strip(), None, lineBlk['Confidence'], 'No', lineBlk['Page'])
        return
            
    #if Date-currentPage-1 key is None then replace with current value if it is not none
    if lineBlk['Page'] > 1:
        answerObj = respDictionary['Date-' + str(lineBlk['Page']-1)]
        if answerObj.answerConfidence is None:
            respDictionary['Date-' + str(lineBlk['Page']-1)] = questionAndAnswersData(lineBlk['Confidence'], lineBlk['Text'].strip(), None, lineBlk['Confidence'], 'No', lineBlk['Page']-1)
    return

    #If no match found, add default values
    if 'Identifier-' + str(lineBlk['Page']) not in respDictionary.keys():
        respDictionary['Identifier-' + str(lineBlk['Page'])] = questionAndAnswersData(lineBlk['Confidence'], None, None, None, 'No', lineBlk['Page'])
        return
    
    if 'Name-' + str(lineBlk['Page']) not in respDictionary.keys():
        respDictionary['Name-' + str(lineBlk['Page'])] = questionAndAnswersData(lineBlk['Confidence'], None, None, None, 'No', lineBlk['Page'])
        return
    
    if 'Date-' + str(lineBlk['Page']) not in respDictionary.keys():
        respDictionary['Date-' + str(lineBlk['Page'])] = questionAndAnswersData(lineBlk['Confidence'], None, None, None, 'No', lineBlk['Page'])
        return

def DoesTextExistsInHRAQuestionBank(strQuestionText, page, trackingQuestions):
    strText = ''
    formattedText = re.sub('^[^A-Za-z]+|[^A-Za-z]+$', '', strQuestionText)
    if len(formattedText) <= 10: # Assuming no question text is less than 10 characters. This is to avoid considering handwritten text as question
        return False, strText
    if formattedText == "days" or formattedText=="months" or formattedText=="years":
        return False, strText
    if formattedText=='ft' or formattedText=='in':
        return False, strText 

    result = [question for question in trackingQuestions if formattedText in question]
    if len(result) > 0:
        strQuestionText = result[0]
        return len(result) > 0, strQuestionText
    else:
        dietQuestion = None
        if 'Are you on a special diet recommended by your doctor?' in formattedText:
            dietQuestion = "11. " + formattedText
            formattedText = '11. Are you on a special diet recommended by your doctor? If yes, what type:'
        for question in trackingQuestions:
            formattedQuestion = re.sub('^[^A-Za-z]+|[^A-Za-z]+$', '', question)
            Comparisonscore = difflib.SequenceMatcher(None, formattedQuestion.lower(), formattedText.lower()).ratio()
            if Comparisonscore > 0.90:
                if dietQuestion is None:
                    if "4" in strQuestionText and "weight" in strQuestionText.lower():
                        question = "4. What is your current weight?"
                    return True, question
                else:
                    return True, dietQuestion
        if "Are you on a special" in formattedText:
            return True, "11. Are you on a special diet recommended by your doctor? If yes, what type"
        if "medications" in formattedText and "prescribed" in formattedText and "Do you take" in formattedText:
            return True, "3. Do you take your medications as prescribed?"
        if page == 1 and "medications" in formattedText and "How many" in formattedText:
            return True, "2. How many medications do you take?"
        if page == 1 and "medications" in formattedText or "prescribed" in formattedText:
            return True, "3. Do you take your medications as prescribed?"
        if "mehcanical soft diet" in formattedText:
            return True, "If yes, diet type?"
    return False, strQuestionText  

def FormatCaregiverAnswers(lineBlk, answerList, questionConfidence, currentProcessingQuestion, results):
    if lineBlk['Text'].strip() == "Caregiver Name:" or lineBlk['Text'].strip() == "Caregiver Relationship to you:":
        return
    if len(answerList) ==2:
        return
    wordBlks= filter(lambda wblk: (wblk['BlockType'] == 'WORD' and wblk['Text'] in lineBlk['Text'] and wblk['Id'] == lineBlk['Relationships'][0]['Ids'][0]), results['Blocks']) 
    IsHandWritten = 'No'
    for wordBlk in wordBlks:
        if(wordBlk['TextType'] == 'HANDWRITING'):
            IsHandWritten = 'Yes'                                           
            break 
    if len(answerList) == 0:
        pattern = r'^[A-Za-z ]+S'
        matches = re.search(pattern, lineBlk['Text'])
        if matches is None:
            lineBlk['Text'] = "Caregiver Name: " + lineBlk['Text']
    if len(answerList) == 1:
        pattern = r'^[A-Za-z ]+S'
        matches = re.search(pattern, lineBlk['Text'])
        if matches is None:
            lineBlk['Text'] = "Caregiver Relationship to you: " + lineBlk['Text']
    
    answer = questionAndAnswersData(questionConfidence, lineBlk['Text'].replace("'",''), None, lineBlk['Confidence'], IsHandWritten, lineBlk['Page'])
    answerList.append(answer)




def FormatHeightAndWeigtAnswers(lineBlk, answerList, questionConfidence, currentProcessingQuestion, results):
    if ((lineBlk['Text'].strip() == "ft" or lineBlk['Text'].strip() == "lbs" or lineBlk['Text'].strip() == "feet" or lineBlk['Text'].strip() == "inches") and len(answerList) > 0):
        return    
    
    # if no inches provided in the answer    
    if (lineBlk['Text'].strip() == "in") and currentProcessingQuestion == '3. What is your current height?':
        if len(answerList) == 1:
            answer = questionAndAnswersData(questionConfidence, lineBlk['Text'], None, lineBlk['Confidence'], 'No', lineBlk['Page'])
            answerList.append(answer)  
            return
        
        if len(answerList) == 2:
            return
    
    wordBlks= filter(lambda wblk: (wblk['BlockType'] == 'WORD' and wblk['Text'] in lineBlk['Text'] and wblk['Id'] == lineBlk['Relationships'][0]['Ids'][0]), results['Blocks']) 
    IsHandWritten = 'No'
    for wordBlk in wordBlks:
        if(wordBlk['TextType'] == 'HANDWRITING'):
            IsHandWritten = 'Yes'                                           
            break  

    if len(answerList) == 0 and currentProcessingQuestion == '3. What is your current height?':
        pattern = r'\d+(\.\d+)?\s*ft'
        matches = re.search(pattern, lineBlk['Text'])
        if matches is None:
            lineBlk['Text'] = lineBlk['Text'] + " ft"
    if len(answerList) == 1 and currentProcessingQuestion == '3. What is your current height?':
        pattern = r'\d+(\.\d+)?\s*in'
        matches = re.search(pattern, lineBlk['Text'])
        if matches is None:
            lineBlk['Text'] = lineBlk['Text'] + " in"
    if len(answerList) == 0 and currentProcessingQuestion == '4. What is your current weight?':
        pattern = r'\d+(\.\d+)?\s*lbs'
        matches = re.search(pattern, lineBlk['Text'])
        if matches is None:
            lineBlk['Text'] = lineBlk['Text'] + " lbs"
    
    if "ft" in lineBlk["Text"].strip():
        strFeet =lineBlk["Text"].strip()[:lineBlk["Text"].strip().index("ft")].strip()
        strFeet = strFeet.replace("s", "5").replace("S", "5")
        lineBlk['Text'] = strFeet + " ft"
    
    if "in" in lineBlk["Text"].strip():
        strFeet = lineBlk["Text"].strip()[:lineBlk["Text"].strip().index("in")].strip()
        strFeet = strFeet.replace("s", "5").replace("S", "5")
        lineBlk['Text'] = strFeet + " in" 

    if "lbs" in lineBlk["Text"].strip():
        strFeet = lineBlk["Text"].strip()[:lineBlk["Text"].strip().index("lbs")].strip()
        strFeet = strFeet.replace("s", "5").replace("S", "5")
        lineBlk['Text'] = strFeet + " lbs" 

    answer = questionAndAnswersData(questionConfidence, lineBlk['Text'].replace("'",''), None, lineBlk['Confidence'], IsHandWritten, lineBlk['Page'])
    answerList.append(answer)

def ReValidateMedicalConditions(answerList, document, questionConfidence):
    try:
        medTable = None
        for tb in document.tables:
            if tb.page == 1 and "High" in tb.text and "cholesterol" in tb.text and "Kidney" in tb.text and "Diabetes" in tb.text and "Depression"  in tb.text and "Arthritis" in tb.text:
                medTable = tb
                break
                
        CheckBoxSelectionHelper.GetCheckBoxAnswerFromDocumentByText("High cholesterol",  document.checkboxes, questionConfidence, answerList, medTable)
        CheckBoxSelectionHelper.GetCheckBoxAnswerFromDocumentByText("Kidney disease",  document.checkboxes, questionConfidence, answerList, medTable)
        CheckBoxSelectionHelper.GetCheckBoxAnswerFromDocumentByText("High blood pressure",  document.checkboxes, questionConfidence, answerList, medTable)
        CheckBoxSelectionHelper.GetCheckBoxAnswerFromDocumentByText("Arthritis",  document.checkboxes, questionConfidence, answerList, medTable)
        CheckBoxSelectionHelper.GetCheckBoxAnswerFromDocumentByText("Diabetes",  document.checkboxes, questionConfidence, answerList, medTable)
        CheckBoxSelectionHelper.GetCheckBoxAnswerFromDocumentByText("Stroke, mini-stroke, TIA",  document.checkboxes, questionConfidence, answerList, medTable)
        CheckBoxSelectionHelper.GetCheckBoxAnswerFromDocumentByText("Congestive heart failure (CHF)",  document.checkboxes, questionConfidence, answerList, medTable)
        CheckBoxSelectionHelper.GetCheckBoxAnswerFromDocumentByText("Depression or anxiety",  document.checkboxes, questionConfidence, answerList, medTable)
        CheckBoxSelectionHelper.GetCheckBoxAnswerFromDocumentByText("Bipolar Disorder or Schizophrenia",  document.checkboxes, questionConfidence, answerList, medTable)
        CheckBoxSelectionHelper.GetCheckBoxAnswerFromDocumentByText("Sleep disturbances",  document.checkboxes, questionConfidence, answerList, medTable)
        CheckBoxSelectionHelper.GetCheckBoxAnswerFromDocumentByText("Dementia or Alzheimer''s disease",  document.checkboxes, questionConfidence, answerList, medTable)
        CheckBoxSelectionHelper.GetCheckBoxAnswerFromDocumentByText("Chronic pain or Fibromyalgia",  document.checkboxes, questionConfidence, answerList, medTable)
        CheckBoxSelectionHelper.GetCheckBoxAnswerFromDocumentByText("Hearing Problems",  document.checkboxes, questionConfidence, answerList, medTable)
        CheckBoxSelectionHelper.GetCheckBoxAnswerFromDocumentByText("Vision Problems",  document.checkboxes, questionConfidence, answerList, medTable)
        CheckBoxSelectionHelper.GetCheckBoxAnswerFromDocumentByText("Asthma",  document.checkboxes, questionConfidence, answerList, medTable)
        CheckBoxSelectionHelper.GetCheckBoxAnswerFromDocumentByText("Organ Transplant",  document.checkboxes, questionConfidence, answerList, medTable)
        CheckBoxSelectionHelper.GetCheckBoxAnswerFromDocumentByText("Heart Conditions",  document.checkboxes, questionConfidence, answerList,medTable)
        CheckBoxSelectionHelper.GetCheckBoxAnswerFromDocumentByText("Bone Disorder",  document.checkboxes, questionConfidence, answerList, medTable)
        CheckBoxSelectionHelper.GetCheckBoxAnswerFromDocumentByText("Chronic Obstructive Pulmonary Disease (COPD/Emphysema)",  document.checkboxes, questionConfidence, answerList, medTable)

        CheckBoxSelectionHelper.GetCheckBoxAnswerFromDocumentByText("Autoimmune disorder",  document.checkboxes, questionConfidence, answerList, medTable)
        CheckBoxSelectionHelper.GetCheckBoxAnswerFromDocumentByText("Blood disorder",  document.checkboxes, questionConfidence, answerList, medTable)
        CheckBoxSelectionHelper.GetCheckBoxAnswerFromDocumentByText("Bone disorder",  document.checkboxes, questionConfidence, answerList, medTable)
        CheckBoxSelectionHelper.GetCheckBoxAnswerFromDocumentByText("Chronic mental conditions (e.g., bipolar disorder or schizophrenia)", document.checkboxes, questionConfidence, answerList, medTable)
        CheckBoxSelectionHelper.GetCheckBoxAnswerFromDocumentByText("Chronic pain (e.g. persistent back or fibromyalgia)",  document.checkboxes, questionConfidence, answerList, medTable)
        CheckBoxSelectionHelper.GetCheckBoxAnswerFromDocumentByText("Lung disorder (e.g., asthma, emphysema, chronic obstructive pulmonary disease (COPD))",  document.checkboxes, questionConfidence, answerList, medTable)





    except Exception as ex:
        print('Exception while processing mediacal conditions: ', ex)
        # no need to abort the process, continue and get answers for rest of the questions
        pass




lambda_handler(1,22)
