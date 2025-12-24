from Questionaire import questionAndAnswersData
import HRAHelper

def GetCheckBoxAnswerFromDocument(chkBoxes, lineBlk, questionConfidence, answerList):
    lblName = lineBlk['Text'].strip()
    if  lblName == 'Native' and len(answerList) == 3:
        lblName = lblName + " Hawaiian"
    elif  lblName == 'African' or lblName == 'Native' or lblName == 'Indian':
        lblName = lblName + " American"
    elif  lblName == 'Pacific':
        lblName = lblName + " Islander"    
    
    for chkBox in chkBoxes:
        if "High" in chkBox.words.text:
            answer = questionAndAnswersData(questionConfidence, lblName, 'NOT_SELECTED', 0, 'No', lineBlk['Page'], None)    
            answerList.append(answer)
            break

        if chkBox == lineBlk['Text'].strip():
            answer = questionAndAnswersData(questionConfidence, lblName, chkBox.selection_status.name, chkBox.Confidence, 'No', lineBlk['Page'], None)    
            answerList.append(answer)
            return

def GetCheckBoxAnswerFromDocumentByText(medicalCondition, checkboxes, questionConfidence, answerList, medicationTable):

    if [item for item in answerList if item.answerText == medicalCondition]:
        return
    
    chkVal = filter(lambda chkBox: (chkBox.words.text == medicalCondition and chkBox.page == 1 and chkBox._raw_object['BlockType'] == 'KEY_VALUE_SET'), checkboxes)
    for chkBox in chkVal:
        print("Revalidation-:" + medicalCondition + " status ")
        answer = questionAndAnswersData(questionConfidence, medicalCondition, chkBox.selection_status.name, chkBox.confidence * 100, 'No', 1)
        answerList.append(answer) 
        return
    
    for tbCell in medicationTable.table_cells:
        if medicalCondition in tbCell.text and '[X]' in tbCell.text:
            answer = questionAndAnswersData(questionConfidence, medicalCondition, 'SELECTED', tbCell.confidence * 100, 'No', 1)
            answerList.append(answer)
            return
    
        
def GetCheckBoxStatus(checkBoxName, pageNum, childID, answerList, questionConfidence, checkboxes):
    chkVal = filter(lambda chkBox: (chkBox.words.text == checkBoxName and chkBox.page == pageNum and chkBox._raw_object['BlockType'] == 'KEY_VALUE_SET'), checkboxes)
    for chkBox in chkVal:
        print(chkBox)
        for relationship in chkBox._raw_object['Relationships']:
            if relationship['Type'] == 'CHILD' and childID in relationship['Ids']:
                answer = questionAndAnswersData(questionConfidence, checkBoxName, chkBox.selection_status.name, chkBox.confidence * 100, 'No', pageNum)
                answerList.append(answer) 
                return
    
    if  'Cancer; If yes, what type' in checkBoxName:
        chkVal = filter(lambda chkBox: ('Cancer; If yes, what type' in chkBox.words.text and chkBox.page == pageNum and chkBox._raw_object['BlockType'] == 'KEY_VALUE_SET'), checkboxes)
        for chkBox in chkVal:
            print(chkBox)
            for relationship in chkBox._raw_object['Relationships']:
                if relationship['Type'] == 'CHILD' and childID in relationship['Ids']:
                    answer = questionAndAnswersData(questionConfidence, checkBoxName, chkBox.selection_status.name, chkBox.confidence * 100, 'No', pageNum, None)
                    answerList.append(answer) 
                    return

def CheckCheckBoxAnswer(lineBlk, results, answerList, questionConfidence, checkboxes):
    if 'Relationships' in lineBlk:       
        for lineId in lineBlk['Relationships'][0]['Ids']:
            kvsBlks =  filter(lambda blk: (blk['BlockType'] == 'KEY_VALUE_SET'), results['Blocks'])
            childBlkFound = False
            valueId = None              
            for kvBlk in kvsBlks:
                if 'KEY' not in kvBlk['EntityTypes']:
                    continue
                if 'Relationships' not in kvBlk:
                    continue
                
                for kvrelations in kvBlk['Relationships']:
                    if kvrelations['Type'] == 'CHILD' and lineId in kvrelations['Ids']:
                        childBlkFound = True                      

                    if kvrelations['Type'] == 'VALUE':
                        valueId = kvrelations['Ids'][0]

                if childBlkFound and valueId is not None:
                    break
        formattedAnswer = lineBlk['Text']
        if "-" in lineBlk['Text']:
            formattedAnswer = HRAHelper.FormatAnswerText(lineBlk['Text'])

        final_KV_Bln =  filter(lambda blk: (blk['BlockType'] == 'KEY_VALUE_SET' and blk['Id']==valueId), results['Blocks'])
        for kvBlk in final_KV_Bln:
            if 'VALUE' in kvBlk['EntityTypes']:
                if 'Relationships' not in kvBlk:
                    continue
                for kvRelations in kvBlk['Relationships']:
                    if kvRelations['Type'] == 'CHILD':
                        selectionBlk =  filter(lambda blk: (blk['BlockType'] == 'SELECTION_ELEMENT' and blk['Id'] == kvRelations['Ids'][0]), results['Blocks'])
                        for resultBlk in selectionBlk:
                            print(f"{resultBlk['SelectionStatus']} - {resultBlk['Confidence']}")
                            if lineBlk['Text'].startswith('Other'):
                                lblNameArr = lineBlk['Text'].split(' ')
                                answer = questionAndAnswersData(questionConfidence, lblNameArr[0], resultBlk['SelectionStatus'], resultBlk['Confidence'], 'No', lineBlk['Page'], lblNameArr[1] if len(lblNameArr) > 1 else None)
                            else:
                                answer = questionAndAnswersData(questionConfidence, formattedAnswer, resultBlk['SelectionStatus'], resultBlk['Confidence'], 'No', lineBlk['Page'], None)
                            answerList.append(answer)
                            return
        if 'Between' in formattedAnswer and 'years' in formattedAnswer:
            answer = questionAndAnswersData(questionConfidence, formattedAnswer, 'NOT_SELECTED', 0, 'No', lineBlk['Page'], None)
            answerList.append(answer)
            return
        
        chkVal = filter(lambda chkBox: (chkBox.words.text in lineBlk['Text'] and chkBox.page == lineBlk['Page'] and chkBox._raw_object['BlockType'] == 'KEY_VALUE_SET'), checkboxes)
        for chkBox in chkVal:
            print(chkBox)
            answer = questionAndAnswersData(questionConfidence, formattedAnswer, chkBox.selection_status.name, chkBox.confidence * 100, 'No', lineBlk['Page'])
            answerList.append(answer) 
            return
                
        # In some instances, checkbox is coming as not selected even though selected.
        # if "Cancer; If Yes, waht type" question contains any additional text after end of the question then consider checkbox as selected.
        if 'Cancer' in formattedAnswer and 'If yes' in formattedAnswer and 'what type' in formattedAnswer:
            cancerText = formattedAnswer.split()[-1]
            if "type" not in cancerText.lower()  and ":" not in cancerText:
                answer = questionAndAnswersData(questionConfidence, formattedAnswer, 'SELECTED', 0, 'No', lineBlk['Page'], None)
                answerList.append(answer)
            else:
                answer = questionAndAnswersData(questionConfidence, formattedAnswer, 'NOT_SELECTED', 0, 'No', lineBlk['Page'], None)
                answerList.append(answer)
        
        if "Over" in lineBlk['Text'] and "5" in lineBlk['Text'] and "years" in lineBlk['Text'] and lineBlk['Page'] == 2:
            answer = questionAndAnswersData(questionConfidence, formattedAnswer, 'NOT_SELECTED', 0, 'No', lineBlk['Page'], None)
            answerList.append(answer)

def CheckCheckBoxValues(lineBlk, results, answerList, questionConfidence):
    if 'Relationships' in lineBlk:       
        for lineId in lineBlk['Relationships'][0]['Ids']:
            cellBlks =  filter(lambda blk: (blk['BlockType'] == 'CELL'), results['Blocks'])              
            for cellBlk in cellBlks:
               
                if 'Relationships' not in cellBlk:
                    continue

                for kvrelations in cellBlk['Relationships']:
                    if kvrelations['Type'] != 'CHILD':
                        continue

                    if lineId not in kvrelations['Ids']:
                        continue

                    for id in kvrelations['Ids']:
                        selectionBlk =  filter(lambda blk: (blk['BlockType'] == 'SELECTION_ELEMENT' and blk['Id'] == id), results['Blocks'])
                        lblName = lineBlk['Text']
                        for sBlk in selectionBlk:
                            if cellBlk['RowIndex'] == 1 and (cellBlk['ColumnIndex']==1 or cellBlk['ColumnIndex']==2 or cellBlk['ColumnIndex']==5):
                                lblName = lineBlk['Text'] + ' ' + 'American'

                            if cellBlk['RowIndex'] == 1 and cellBlk['ColumnIndex']==3:
                                lblName = lineBlk['Text'] + ' ' + 'Islander'
                            
                            if cellBlk['RowIndex'] == 1 and cellBlk['ColumnIndex']==4:
                               lblName = lineBlk['Text'] + ' ' + 'Hawaiian'

                            print(f"{lineBlk['Text'] + ' ' + 'Hawaiian'}:-{lineBlk['Confidence']}")
                            print(f"{sBlk['SelectionStatus']} - {sBlk['Confidence']}")
                            if lblName.startswith('Other'):
                               lblNameArr= lblName.split(' ')
                               answer = questionAndAnswersData(questionConfidence, lblNameArr[0], sBlk['SelectionStatus'], sBlk['Confidence'], 'No', lineBlk['Page'], lblNameArr[1] if len(lblNameArr) > 1 else None)
                            else:
                                answer = questionAndAnswersData(questionConfidence, lblName, sBlk['SelectionStatus'], sBlk['Confidence'], 'No', lineBlk['Page'], None)
                            answerList.append(answer)
                            return
